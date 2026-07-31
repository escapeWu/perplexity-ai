"""Tests for the development-side GitHub model catalog publisher."""

import json
from pathlib import Path
from typing import Any

import pytest

from perplexity import model_catalog_sync
from perplexity.model_catalog_sync import CatalogSyncError


def sample_catalog() -> dict[str, Any]:
    return {
        "config_schema": "v2",
        "default_models": {"search": "pplx_pro", "research": "pplx_alpha"},
        "models": {
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


def test_write_catalog_publishes_raw_v2_json_atomically(tmp_path: Path) -> None:
    output = tmp_path / "catalog" / "model_config_v2.json"

    digest = model_catalog_sync.write_catalog(sample_catalog(), output)
    published = json.loads(output.read_text(encoding="utf-8"))

    assert len(digest) == 64
    assert published["config_schema"] == "v2"
    assert "cache_schema" not in published
    assert output.stat().st_mode & 0o777 == 0o644
    assert not list(output.parent.glob("*.tmp"))
    assert model_catalog_sync.catalog_summary(published) == {
        "models": 4,
        "search_entries": 2,
        "pro_entries": 1,
        "max_entries": 1,
        "usable_models": 8,
    }


def test_repository_snapshot_is_valid_and_contains_pro_and_max_models() -> None:
    snapshot = Path(__file__).parents[1] / "catalog" / "model_config_v2.json"

    catalog = model_catalog_sync.load_catalog(snapshot)
    summary = model_catalog_sync.catalog_summary(catalog)

    assert summary["models"] > 0
    assert summary["pro_entries"] > 0
    assert summary["max_entries"] > 0
    assert summary["usable_models"] > 4


def test_load_catalog_rejects_invalid_schema(tmp_path: Path) -> None:
    source = tmp_path / "invalid.json"
    source.write_text(json.dumps({"config_schema": "v1"}), encoding="utf-8")

    with pytest.raises(CatalogSyncError, match="failed validation"):
        model_catalog_sync.load_catalog(source)


def test_fetch_catalog_uses_browser_headers_and_validates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[dict[str, Any]] = []
    monkeypatch.setattr(model_catalog_sync, "SOCKS_PROXY", None)

    class Response:
        ok = True
        status_code = 200
        content = json.dumps(sample_catalog()).encode()

    def fake_get(url: str, **kwargs: Any) -> Response:
        calls.append({"url": url, **kwargs})
        return Response()

    monkeypatch.setattr(model_catalog_sync.requests, "get", fake_get)

    catalog = model_catalog_sync.fetch_catalog("https://example.com/models.json", timeout=12)

    assert catalog["config_schema"] == "v2"
    assert calls == [
        {
            "url": "https://example.com/models.json",
            "headers": {
                **model_catalog_sync.DEFAULT_HEADERS,
                "accept": "application/json",
            },
            "impersonate": "chrome",
            "proxy": None,
            "timeout": 12,
        }
    ]


def test_cli_updates_repository_snapshot_from_local_file(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    source = tmp_path / "downloaded.json"
    output = tmp_path / "catalog" / "model_config_v2.json"
    source.write_text(json.dumps(sample_catalog()), encoding="utf-8")

    result = model_catalog_sync.main(["--input", str(source), "--output", str(output)])

    assert result == 0
    assert json.loads(output.read_text(encoding="utf-8"))["config_schema"] == "v2"
    stdout = capsys.readouterr().out
    assert f"Updated {output}" in stdout
    assert "Review the catalog diff before committing and pushing it." in stdout


def test_fetch_catalog_403_explains_browser_download_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Response:
        ok = False
        status_code = 403
        content = b""

    monkeypatch.setattr(model_catalog_sync.requests, "get", lambda *args, **kwargs: Response())

    with pytest.raises(CatalogSyncError, match="save the JSON"):
        model_catalog_sync.fetch_catalog("https://example.com/models.json")
