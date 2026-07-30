"""Tests for the dynamic, tier-aware Perplexity model catalog."""

import json
import time
from pathlib import Path

from perplexity.model_registry import (
    ModelRegistry,
    account_supports_tier,
    normalize_subscription_tier,
)


def sample_config() -> dict:
    return {
        "config_schema": "v2",
        "default_models": {"search": "pplx_pro", "research": "pplx_alpha"},
        "models": {
            "experimental": {
                "label": "Sonar 2",
                "description": "Perplexity model",
                "mode": "search",
            },
            "browser_sonnet": {
                "label": "Claude Sonnet Browser",
                "description": "Browser agent",
                "mode": "browser_agent",
            },
            "gpt56_terra": {
                "label": "GPT-5.6 Terra",
                "description": "Versatile",
                "mode": "search",
            },
            "gpt56_terra_thinking": {
                "label": "GPT-5.6 Terra Thinking",
                "description": "Reasoning",
                "mode": "search",
            },
            "gpt56_sol": {
                "label": "GPT-5.6 Sol",
                "description": "Powerful",
                "mode": "search",
            },
            "gpt56_sol_thinking": {
                "label": "GPT-5.6 Sol Thinking",
                "description": "Powerful reasoning",
                "mode": "search",
            },
        },
        "search_config": [
            {
                "label": "Sonar 2",
                "description": "Perplexity model",
                "subscription_tier": "pro",
                "non_reasoning_model": "experimental",
                "reasoning_model": None,
            },
            {
                "label": "Claude Sonnet Browser",
                "description": "Browser agent",
                "subscription_tier": "pro",
                "non_reasoning_model": "browser_sonnet",
                "reasoning_model": None,
            },
            {
                "label": "GPT-5.6 Terra",
                "description": "Versatile",
                "subscription_tier": "pro",
                "non_reasoning_model": "gpt56_terra",
                "reasoning_model": "gpt56_terra_thinking",
            },
            {
                "label": "GPT-5.6 Sol",
                "description": "Powerful",
                "subscription_tier": "max",
                "non_reasoning_model": "gpt56_sol",
                "reasoning_model": "gpt56_sol_thinking",
            },
        ],
    }


def registry_with_config(tmp_path: Path) -> ModelRegistry:
    registry = ModelRegistry(cache_path=tmp_path / "models.json")
    registry._fetch_config = lambda: sample_config()  # type: ignore[method-assign]
    assert registry.refresh() is True
    return registry


def test_catalog_filters_browser_agents_and_splits_pro_max(tmp_path: Path) -> None:
    registry = registry_with_config(tmp_path)

    pro = registry.get_model_mappings({"pro"})
    max_account = registry.get_model_mappings({"max"})

    assert pro["pro"]["gpt-5.6-terra"] == "gpt56_terra"
    assert "gpt-5.6-sol" not in pro["pro"]
    assert max_account["pro"]["gpt-5.6-sol"] == "gpt56_sol"
    assert max_account["reasoning"]["gpt-5.6-sol-thinking"] == "gpt56_sol_thinking"
    assert "claude-sonnet-browser" not in max_account["pro"]


def test_oai_models_include_catalog_metadata_and_round_trip(tmp_path: Path) -> None:
    registry = registry_with_config(tmp_path)

    pro_models = registry.generate_oai_models({"pro"})
    max_models = registry.generate_oai_models({"max"})
    pro_ids = {model["id"] for model in pro_models}
    max_ids = {model["id"] for model in max_models}

    assert "gpt-5-6-sol" not in pro_ids
    assert {"gpt-5-6-sol", "gpt-5-6-sol-thinking"} <= max_ids
    sol = next(model for model in max_models if model["id"] == "gpt-5-6-sol")
    assert sol["label"] == "GPT-5.6 Sol"
    assert sol["subscription_tier"] == "max"
    assert sol["mode"] == "pro"
    assert registry.parse_oai_model("gpt-5-6-sol", {"max"}) == (
        "pro",
        "gpt-5.6-sol",
    )


def test_refresh_writes_cache_and_fresh_instance_loads_it(tmp_path: Path) -> None:
    cache_path = tmp_path / "nested" / "models.json"
    registry = ModelRegistry(cache_path=cache_path)
    registry._fetch_config = lambda: sample_config()  # type: ignore[method-assign]

    assert registry.refresh() is True
    assert cache_path.exists()
    assert not list(cache_path.parent.glob("*.tmp"))

    loaded = ModelRegistry(cache_path=cache_path)
    assert loaded.status["source"] == "cache"
    assert loaded.is_stale() is False
    assert loaded.get_model_mappings({"max"})["pro"]["gpt-5.6-sol"] == "gpt56_sol"


def test_stale_cache_survives_refresh_failure(tmp_path: Path) -> None:
    cache_path = tmp_path / "models.json"
    registry = registry_with_config(tmp_path)
    envelope = json.loads(cache_path.read_text(encoding="utf-8"))
    envelope["fetched_at"] = time.time() - 100
    cache_path.write_text(json.dumps(envelope), encoding="utf-8")

    loaded = ModelRegistry(cache_path=cache_path, ttl_seconds=10)

    def fail_fetch() -> dict:
        raise RuntimeError("network unavailable")

    loaded._fetch_config = fail_fetch  # type: ignore[method-assign]
    assert loaded.is_stale() is True
    assert loaded.refresh_if_stale() is False
    assert loaded.get_model_mappings({"max"})["pro"]["gpt-5.6-sol"] == "gpt56_sol"


def test_corrupt_cache_falls_back_to_built_in_models(tmp_path: Path) -> None:
    cache_path = tmp_path / "models.json"
    cache_path.write_text("{broken", encoding="utf-8")

    registry = ModelRegistry(cache_path=cache_path)

    assert registry.status["source"] == "static"
    assert registry.get_model_mappings({"pro"})["pro"]["gpt-5.6-terra"] == "gpt56_terra"


def test_account_tier_normalization_is_conservative_for_max() -> None:
    assert normalize_subscription_tier("MAX") == "max"
    assert normalize_subscription_tier("pro") == "pro"
    assert normalize_subscription_tier(None, own_account=False) == "free"
    assert account_supports_tier("max", "pro") is True
    assert account_supports_tier("pro", "max") is False
    assert account_supports_tier("unknown", "pro") is True
    assert account_supports_tier("unknown", "max") is False
