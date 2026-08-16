"""Dynamic Perplexity model catalog with a persistent daily cache."""

from __future__ import annotations

import json
import logging
import os
import re
import tempfile
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Tuple

from .config import (
    ENDPOINT_MODELS_CONFIG,
    MODEL_CONFIG_CACHE_TTL,
    MODEL_MAPPINGS,
    SOCKS_PROXY,
)

logger = logging.getLogger(__name__)

CACHE_SCHEMA = 1
MODEL_TIERS = frozenset({"pro", "max"})


def normalize_subscription_tier(value: Any, *, own_account: bool = True) -> str:
    """Normalize the account tier returned by ``/api/auth/session``."""
    if not own_account:
        return "free"
    tier = str(value or "").strip().lower()
    if tier == "max":
        return "max"
    if tier == "pro":
        return "pro"
    if tier in {"free", "anonymous"}:
        return "free"
    return "unknown"


def account_supports_tier(account_tier: str, required_tier: Optional[str]) -> bool:
    """Return whether an account can execute a model of ``required_tier``."""
    if required_tier is None:
        return True
    normalized = normalize_subscription_tier(account_tier)
    if required_tier == "max":
        return normalized == "max"
    if required_tier == "pro":
        # Older/mocked sessions may omit the tier. Preserve existing Pro
        # behavior while never allowing an unknown account to run Max models.
        return normalized in {"pro", "max", "unknown"}
    return False


def default_model_cache_path() -> Path:
    """Resolve a writable, server-local cache path."""
    configured = os.getenv("PPLX_MODEL_CACHE_PATH")
    if configured:
        return Path(configured).expanduser()

    token_config = os.getenv("PPLX_TOKEN_POOL_CONFIG")
    if token_config:
        return Path(token_config).expanduser().resolve().parent / "model_config_v2.json"

    return Path.cwd() / ".cache" / "perplexity" / "model_config_v2.json"


def sanitize_oai_model_name(name: str) -> str:
    """Convert an MCP model name into an OpenAI-compatible model id."""
    return name.lower().replace(".", "-").replace(" ", "-")


def oai_model_id(mode: str, model_name: Optional[str]) -> str:
    """Compute the stable OpenAI id for a mode/model pair."""
    if model_name is None:
        if mode == "reasoning":
            return "perplexity-thinking"
        if mode == "deep research":
            return "perplexity-deepsearch"
        return "perplexity-search"

    sanitized = sanitize_oai_model_name(model_name)
    if mode == "reasoning":
        if sanitized.endswith("-thinking"):
            return sanitized
        if sanitized.endswith("-reasoning"):
            return sanitized[: -len("-reasoning")] + "-thinking"
        return sanitized + "-thinking"
    return sanitized


def _slugify_label(label: str) -> str:
    value = re.sub(r"[^a-z0-9.]+", "-", label.lower()).strip("-")
    return value or "model"


@dataclass(frozen=True)
class ModelDefinition:
    mode: str
    public_name: Optional[str]
    internal_id: str
    subscription_tier: Optional[str]
    label: str
    description: str = ""
    alias: bool = False

    @property
    def oai_id(self) -> str:
        return oai_model_id(self.mode, self.public_name)


class ModelRegistry:
    """Thread-safe model registry backed by Perplexity's public v2 catalog."""

    def __init__(
        self,
        cache_path: Optional[Path | str] = None,
        ttl_seconds: int = MODEL_CONFIG_CACHE_TTL,
        endpoint: str = ENDPOINT_MODELS_CONFIG,
    ) -> None:
        self.cache_path = Path(cache_path) if cache_path else default_model_cache_path()
        self.ttl_seconds = ttl_seconds
        self.endpoint = endpoint
        self._lock = threading.RLock()
        self._refresh_lock = threading.Lock()
        self._definitions = self._fallback_definitions()
        self._raw_config: Optional[Dict[str, Any]] = None
        self._fetched_at = 0.0
        self._source = "static"
        self._load_cache()

    @staticmethod
    def _fallback_definitions() -> List[ModelDefinition]:
        definitions: List[ModelDefinition] = []
        for mode, mappings in MODEL_MAPPINGS.items():
            for public_name, internal_id in mappings.items():
                alias = mode == "pro" and public_name == "sonar"
                label = "Best" if public_name is None else public_name.replace("-", " ").title()
                definitions.append(
                    ModelDefinition(
                        mode=mode,
                        public_name=public_name,
                        internal_id=internal_id,
                        subscription_tier=None if mode == "auto" else "pro",
                        label=label,
                        alias=alias,
                    )
                )
        return definitions

    @staticmethod
    def _preferred_names() -> Dict[Tuple[str, str], str]:
        names: Dict[Tuple[str, str], str] = {}
        for mode, mappings in MODEL_MAPPINGS.items():
            for public_name, internal_id in mappings.items():
                if public_name is None or public_name == "sonar":
                    continue
                names.setdefault((mode, internal_id), public_name)
        return names

    @classmethod
    def _definitions_from_config(cls, config: Mapping[str, Any]) -> List[ModelDefinition]:
        if config.get("config_schema") != "v2":
            raise ValueError("Unsupported model config schema")
        models = config.get("models")
        search_config = config.get("search_config")
        if not isinstance(models, dict) or not isinstance(search_config, list):
            raise ValueError("Model config is missing models/search_config")

        default_models = config.get("default_models")
        if not isinstance(default_models, dict):
            default_models = {}

        definitions: List[ModelDefinition] = [
            ModelDefinition("auto", None, "turbo", None, "Best"),
            ModelDefinition(
                "pro",
                None,
                str(default_models.get("search") or "pplx_pro"),
                "pro",
                "Best",
                "Automatically selects the best available model",
            ),
            # These stable service modes are not represented by search_config,
            # but remain part of the public API.
            ModelDefinition(
                "reasoning",
                None,
                MODEL_MAPPINGS["reasoning"][None],
                "pro",
                "Best Thinking",
            ),
            ModelDefinition(
                "deep research",
                None,
                str(default_models.get("research") or "pplx_alpha"),
                "pro",
                "Deep Research",
            ),
        ]
        preferred_names = cls._preferred_names()

        for item in search_config:
            if not isinstance(item, dict):
                continue
            tier = str(item.get("subscription_tier") or "").lower()
            if tier not in MODEL_TIERS:
                continue
            label = str(item.get("label") or "").strip()
            description = str(item.get("description") or "")
            non_reasoning = item.get("non_reasoning_model")
            reasoning = item.get("reasoning_model")

            variants = (
                ("pro", non_reasoning, False),
                ("reasoning", reasoning, bool(non_reasoning)),
            )
            for mode, internal_id, paired_reasoning in variants:
                if not isinstance(internal_id, str) or not internal_id:
                    continue
                model_metadata = models.get(internal_id)
                # search_config also contains browser-agent choices. They use
                # a different request protocol and must not be sent to /ask.
                if not isinstance(model_metadata, dict) or model_metadata.get("mode") != "search":
                    continue

                public_name = preferred_names.get((mode, internal_id))
                if public_name is None:
                    public_name = _slugify_label(label or model_metadata.get("label", internal_id))
                    if mode == "reasoning" and paired_reasoning:
                        public_name += "-thinking"

                definitions.append(
                    ModelDefinition(
                        mode=mode,
                        public_name=public_name,
                        internal_id=internal_id,
                        subscription_tier=tier,
                        label=label or str(model_metadata.get("label") or public_name),
                        description=description or str(model_metadata.get("description") or ""),
                    )
                )

        if len(definitions) <= 4:
            raise ValueError("Model config contains no usable search models")

        # Preserve the historical Sonar alias without exposing a duplicate in
        # model discovery.
        sonar = next(
            (
                definition
                for definition in definitions
                if definition.mode == "pro" and definition.public_name == "sonar-2"
            ),
            None,
        )
        if sonar is not None:
            definitions.append(
                ModelDefinition(
                    mode=sonar.mode,
                    public_name="sonar",
                    internal_id=sonar.internal_id,
                    subscription_tier=sonar.subscription_tier,
                    label=sonar.label,
                    description=sonar.description,
                    alias=True,
                )
            )
        return definitions

    @staticmethod
    def _allowed_tiers(subscription_tiers: Optional[Iterable[str]]) -> set[str]:
        if subscription_tiers is None:
            return set(MODEL_TIERS)
        normalized = {normalize_subscription_tier(tier) for tier in subscription_tiers}
        allowed: set[str] = set()
        if "pro" in normalized or "unknown" in normalized:
            allowed.add("pro")
        if "max" in normalized:
            allowed.update({"pro", "max"})
        return allowed

    def _snapshot(
        self, subscription_tiers: Optional[Iterable[str]] = None
    ) -> List[ModelDefinition]:
        allowed = self._allowed_tiers(subscription_tiers)
        with self._lock:
            return [
                definition
                for definition in self._definitions
                if definition.subscription_tier is None or definition.subscription_tier in allowed
            ]

    def get_model_mappings(
        self, subscription_tiers: Optional[Iterable[str]] = None
    ) -> Dict[str, Dict[Optional[str], str]]:
        mappings: Dict[str, Dict[Optional[str], str]] = {
            "auto": {},
            "pro": {},
            "reasoning": {},
            "deep research": {},
        }
        for definition in self._snapshot(subscription_tiers):
            mappings[definition.mode][definition.public_name] = definition.internal_id
        return mappings

    def resolve(
        self,
        mode: str,
        model: Optional[str],
        account_tier: Optional[str] = None,
    ) -> ModelDefinition:
        for definition in self._snapshot(None):
            if definition.mode == mode and definition.public_name == model:
                if account_tier is not None and not account_supports_tier(
                    account_tier, definition.subscription_tier
                ):
                    raise ValueError(
                        f"Model '{model}' requires a {definition.subscription_tier} account"
                    )
                return definition
        raise ValueError(f"Invalid model '{model}' for mode '{mode}'")

    def required_tier(self, mode: str, model: Optional[str]) -> Optional[str]:
        return self.resolve(mode, model).subscription_tier

    def build_oai_model_map(
        self, subscription_tiers: Optional[Iterable[str]] = None
    ) -> Dict[str, Tuple[str, Optional[str]]]:
        mapping: Dict[str, Tuple[str, Optional[str]]] = {}
        for definition in self._snapshot(subscription_tiers):
            model_id = definition.oai_id
            if (
                model_id not in mapping
                or definition.mode == "pro"
                or mapping[model_id][0] == "auto"
            ):
                mapping[model_id] = (definition.mode, definition.public_name)
        return mapping

    def generate_oai_models(
        self, subscription_tiers: Optional[Iterable[str]] = None
    ) -> List[Dict[str, Any]]:
        selected: Dict[str, ModelDefinition] = {}
        for definition in self._snapshot(subscription_tiers):
            if definition.alias:
                continue
            model_id = definition.oai_id
            existing = selected.get(model_id)
            if existing is None or (existing.mode == "auto" and definition.mode == "pro"):
                selected[model_id] = definition

        models: List[Dict[str, Any]] = []
        for model_id, definition in selected.items():
            base_model_id = model_id
            thinking_model_id: Optional[str] = None
            supports_thinking = False
            thinking = definition.mode == "reasoning"
            thinking_only = False

            if definition.mode == "pro":
                candidate = (
                    "perplexity-thinking"
                    if model_id == "perplexity-search"
                    else f"{model_id}-thinking"
                )
                candidate_definition = selected.get(candidate)
                if candidate_definition is not None and candidate_definition.mode == "reasoning":
                    thinking_model_id = candidate
                    supports_thinking = True
            elif definition.mode == "reasoning":
                candidate = (
                    "perplexity-search"
                    if model_id == "perplexity-thinking"
                    else model_id.removesuffix("-thinking")
                )
                candidate_definition = selected.get(candidate)
                if candidate_definition is not None and candidate_definition.mode == "pro":
                    base_model_id = candidate
                    thinking_model_id = model_id
                    supports_thinking = True
                else:
                    thinking_model_id = model_id
                    thinking_only = True

            models.append(
                {
                    "id": model_id,
                    "object": "model",
                    "created": 1700000000,
                    "owned_by": "perplexity",
                    "label": definition.label,
                    "description": definition.description,
                    "subscription_tier": definition.subscription_tier or "free",
                    "mode": definition.mode,
                    # Pairing metadata lets clients render one upstream-style
                    # model entry while the OAI list keeps both executable IDs.
                    "base_model_id": base_model_id,
                    "thinking_model_id": thinking_model_id,
                    "supports_thinking": supports_thinking,
                    "thinking": thinking,
                    "thinking_only": thinking_only,
                }
            )
        return models

    def parse_oai_model(
        self,
        model_id: str,
        subscription_tiers: Optional[Iterable[str]] = None,
    ) -> Tuple[str, Optional[str]]:
        mapping = self.build_oai_model_map(subscription_tiers)
        if model_id not in mapping:
            raise ValueError(f"Unknown or unavailable model: {model_id}")
        return mapping[model_id]

    @property
    def status(self) -> Dict[str, Any]:
        with self._lock:
            return {
                "source": self._source,
                "fetched_at": self._fetched_at or None,
                "cache_path": str(self.cache_path),
            }

    def is_stale(self, now: Optional[float] = None) -> bool:
        current = time.time() if now is None else now
        with self._lock:
            return not self._fetched_at or current - self._fetched_at >= self.ttl_seconds

    def _load_cache(self) -> bool:
        try:
            with self.cache_path.open("r", encoding="utf-8") as handle:
                cached = json.load(handle)
            if cached.get("cache_schema") != CACHE_SCHEMA:
                raise ValueError("Unsupported model cache schema")
            fetched_at = float(cached["fetched_at"])
            raw_config = cached["config"]
            definitions = self._definitions_from_config(raw_config)
        except FileNotFoundError:
            return False
        except Exception as exc:
            logger.warning("Ignoring invalid model cache %s: %s", self.cache_path, exc)
            return False

        with self._lock:
            self._definitions = definitions
            self._raw_config = dict(raw_config)
            self._fetched_at = fetched_at
            self._source = "cache"
        return True

    def _fetch_config(self) -> Dict[str, Any]:
        from curl_cffi import requests

        proxy = SOCKS_PROXY.split("#", 1)[0] if SOCKS_PROXY else None
        response = requests.get(
            self.endpoint,
            headers={"accept": "application/json"},
            impersonate="chrome",
            proxy=proxy,
            timeout=30,
        )
        if not response.ok:
            raise RuntimeError(f"Model config request failed: HTTP {response.status_code}")
        payload = response.json()
        if not isinstance(payload, dict):
            raise ValueError("Model config response is not an object")
        return payload

    def _write_cache(self, raw_config: Mapping[str, Any], fetched_at: float) -> None:
        envelope = {
            "cache_schema": CACHE_SCHEMA,
            "fetched_at": fetched_at,
            "source_url": self.endpoint,
            "config": raw_config,
        }
        self.cache_path.parent.mkdir(parents=True, exist_ok=True)
        temporary_path: Optional[Path] = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=self.cache_path.parent,
                prefix=f".{self.cache_path.name}.",
                suffix=".tmp",
                delete=False,
            ) as handle:
                temporary_path = Path(handle.name)
                json.dump(envelope, handle, ensure_ascii=False, separators=(",", ":"))
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary_path, self.cache_path)
        finally:
            if temporary_path and temporary_path.exists():
                temporary_path.unlink()

    def refresh(self) -> bool:
        """Fetch, validate, atomically persist, and activate the catalog."""
        with self._refresh_lock:
            raw_config = self._fetch_config()
            definitions = self._definitions_from_config(raw_config)
            fetched_at = time.time()
            self._write_cache(raw_config, fetched_at)
            with self._lock:
                self._definitions = definitions
                self._raw_config = raw_config
                self._fetched_at = fetched_at
                self._source = "remote"
            logger.info("Updated model catalog from %s", self.endpoint)
            return True

    def refresh_if_stale(self) -> bool:
        """Refresh stale data; retain the last valid cache on any failure."""
        if not self.is_stale():
            return False
        try:
            return self.refresh()
        except Exception as exc:
            logger.warning("Model catalog refresh failed; keeping %s data: %s", self._source, exc)
            return False


_registry: Optional[ModelRegistry] = None
_registry_lock = threading.Lock()


def get_model_registry() -> ModelRegistry:
    global _registry
    if _registry is None:
        with _registry_lock:
            if _registry is None:
                _registry = ModelRegistry()
    return _registry


def reset_model_registry() -> None:
    """Reset the singleton (used by tests and controlled reconfiguration)."""
    global _registry
    with _registry_lock:
        _registry = None
