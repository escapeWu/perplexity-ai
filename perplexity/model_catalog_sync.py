"""Publish a validated Perplexity model catalog snapshot for GitHub Raw."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Any, BinaryIO, Dict, Mapping, Optional, Sequence
from urllib.parse import urlsplit

from curl_cffi import requests

from .config import DEFAULT_HEADERS, OFFICIAL_MODELS_CONFIG_URL, SOCKS_PROXY
from .model_registry import ModelRegistry

DEFAULT_OUTPUT_PATH = Path("catalog/model_config_v2.json")
MAX_CATALOG_BYTES = 2 * 1024 * 1024


class CatalogSyncError(RuntimeError):
    """Raised when a catalog cannot be fetched, parsed, or published."""


def _read_limited(stream: BinaryIO, *, source: str) -> bytes:
    payload = stream.read(MAX_CATALOG_BYTES + 1)
    if len(payload) > MAX_CATALOG_BYTES:
        raise CatalogSyncError(f"Catalog from {source} exceeds the {MAX_CATALOG_BYTES}-byte limit")
    return payload


def _parse_catalog(payload: bytes, *, source: str) -> Dict[str, Any]:
    try:
        decoded = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CatalogSyncError(f"Catalog from {source} is not valid UTF-8 JSON: {exc}") from exc
    if not isinstance(decoded, dict):
        raise CatalogSyncError(f"Catalog from {source} must be a JSON object")

    try:
        ModelRegistry._definitions_from_config(decoded)
    except (TypeError, ValueError) as exc:
        raise CatalogSyncError(f"Catalog from {source} failed validation: {exc}") from exc
    return decoded


def load_catalog(path: str | Path) -> Dict[str, Any]:
    """Load and validate a raw v2 catalog from a file or stdin (``-``)."""
    path_text = str(path)
    if path_text == "-":
        return _parse_catalog(_read_limited(sys.stdin.buffer, source="stdin"), source="stdin")

    source_path = Path(path).expanduser()
    try:
        with source_path.open("rb") as handle:
            payload = _read_limited(handle, source=str(source_path))
    except OSError as exc:
        raise CatalogSyncError(f"Unable to read catalog {source_path}: {exc}") from exc
    return _parse_catalog(payload, source=str(source_path))


def fetch_catalog(url: str, *, timeout: float = 30) -> Dict[str, Any]:
    """Fetch and validate a raw v2 catalog from an HTTP(S) endpoint."""
    parsed = urlsplit(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise CatalogSyncError("Catalog URL must use http or https")
    if timeout <= 0:
        raise CatalogSyncError("Catalog timeout must be greater than zero")

    proxy = SOCKS_PROXY.split("#", 1)[0] if SOCKS_PROXY else None
    headers = DEFAULT_HEADERS.copy()
    headers["accept"] = "application/json"
    try:
        response = requests.get(
            url,
            headers=headers,
            impersonate="chrome",
            proxy=proxy,
            timeout=timeout,
        )
    except Exception as exc:
        raise CatalogSyncError(f"Catalog request failed for {url}: {exc}") from exc
    if not response.ok:
        hint = (
            " Open the URL in a browser, save the JSON, and rerun with --input PATH."
            if response.status_code == 403
            else ""
        )
        raise CatalogSyncError(
            f"Catalog request failed for {url}: HTTP {response.status_code}.{hint}"
        )

    return _parse_catalog(response.content, source=url)


def catalog_summary(config: Mapping[str, Any]) -> Dict[str, int]:
    """Return a compact summary used for local review before committing."""
    definitions = ModelRegistry._definitions_from_config(config)
    search_config = config.get("search_config")
    search_items = search_config if isinstance(search_config, list) else []
    return {
        "models": len(config.get("models", {})),
        "search_entries": len(search_items),
        "pro_entries": sum(
            1
            for item in search_items
            if isinstance(item, dict) and item.get("subscription_tier") == "pro"
        ),
        "max_entries": sum(
            1
            for item in search_items
            if isinstance(item, dict) and item.get("subscription_tier") == "max"
        ),
        "usable_models": sum(1 for definition in definitions if not definition.alias),
    }


def serialize_catalog(config: Mapping[str, Any]) -> bytes:
    """Serialize a stable, review-friendly raw catalog file."""
    return (json.dumps(config, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")


def write_catalog(config: Mapping[str, Any], output_path: str | Path) -> str:
    """Atomically write a raw catalog and return its SHA-256 digest."""
    output = Path(output_path)
    serialized = serialize_catalog(config)
    digest = hashlib.sha256(serialized).hexdigest()
    output.parent.mkdir(parents=True, exist_ok=True)

    temporary_path: Optional[Path] = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb",
            dir=output.parent,
            prefix=f".{output.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temporary_path = Path(handle.name)
            handle.write(serialized)
            handle.flush()
            os.fsync(handle.fileno())
            os.chmod(temporary_path, 0o644)
        os.replace(temporary_path, output)
    finally:
        if temporary_path and temporary_path.exists():
            temporary_path.unlink()
    return digest


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Fetch or load Perplexity's v2 model catalog, validate it, and write "
            "the repository snapshot consumed through GitHub Raw."
        )
    )
    source = parser.add_mutually_exclusive_group()
    source.add_argument(
        "--input",
        metavar="PATH",
        help="Read a browser-downloaded JSON file; use - to read stdin",
    )
    source.add_argument(
        "--url",
        metavar="URL",
        help=f"Fetch a catalog URL (default: {OFFICIAL_MODELS_CONFIG_URL})",
    )
    parser.add_argument(
        "--output",
        default=str(DEFAULT_OUTPUT_PATH),
        metavar="PATH",
        help=f"Repository snapshot path (default: {DEFAULT_OUTPUT_PATH})",
    )
    parser.add_argument(
        "--timeout",
        default=30.0,
        type=float,
        help="HTTP timeout in seconds (default: 30)",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Validate and print a summary without writing the snapshot",
    )
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    try:
        config = (
            load_catalog(args.input)
            if args.input
            else fetch_catalog(args.url or OFFICIAL_MODELS_CONFIG_URL, timeout=args.timeout)
        )
        summary = catalog_summary(config)
        serialized = serialize_catalog(config)
        digest = hashlib.sha256(serialized).hexdigest()
        if not args.check:
            digest = write_catalog(config, args.output)
    except CatalogSyncError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    action = "Validated" if args.check else f"Updated {args.output}"
    print(
        f"{action}: models={summary['models']}, search={summary['search_entries']} "
        f"(pro={summary['pro_entries']}, max={summary['max_entries']}), "
        f"usable={summary['usable_models']}, sha256={digest[:16]}"
    )
    if not args.check:
        print("Review the catalog diff before committing and pushing it.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
