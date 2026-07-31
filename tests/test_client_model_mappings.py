"""Verify every model uses canonical mappings and current browser request metadata."""

import json
from pathlib import Path
from typing import Any

import pytest

from perplexity.client import Client as SyncClient
from perplexity.config import DEFAULT_HEADERS, ENDPOINT_SSE_ASK, MODEL_MAPPINGS
from perplexity.model_registry import ModelRegistry


@pytest.fixture(autouse=True)
def static_model_registry(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    """Keep canonical mapping tests independent from a developer's live cache."""
    registry = ModelRegistry(cache_path=tmp_path / "missing-model-cache.json")
    monkeypatch.setattr("perplexity.client.get_model_registry", lambda: registry)


class RecordingSyncSession:
    def __init__(self) -> None:
        self.requests: list[dict[str, Any]] = []

    def post(self, url: str, **kwargs: Any) -> object:
        self.requests.append({"url": url, **kwargs})
        return EmptySyncResponse()


class EmptySyncResponse:
    def iter_lines(self, delimiter: bytes):
        return iter(())

    def close(self) -> None:
        pass


MODEL_CASES = [
    (mode, model, slug)
    for mode, mappings in MODEL_MAPPINGS.items()
    for model, slug in mappings.items()
]


@pytest.mark.parametrize(("mode", "model", "slug"), MODEL_CASES)
def test_sync_client_uses_canonical_model_mapping(mode: str, model: str | None, slug: str) -> None:
    session = RecordingSyncSession()
    client = SyncClient.__new__(SyncClient)
    client.session = session
    client.own = True
    client.copilot = float("inf")
    client.file_upload = float("inf")
    client._user_info = {"user": {"id": "account-id"}}

    stream = client.search("model mapping probe", mode=mode, model=model, stream=True)
    list(stream)

    request = session.requests[0]
    params = request["json"]["params"]
    headers = request["headers"]

    assert params["model_preference"] == slug
    assert headers["accept"] == "text/event-stream"
    assert headers["content-type"] == "application/json"
    assert headers["sec-fetch-dest"] == "empty"
    assert headers["sec-fetch-mode"] == "cors"
    assert headers["x-pplx-account"] == "account-id"
    assert headers["x-request-id"] == params["frontend_uuid"]
    assert "sec-fetch-user" not in headers
    assert "upgrade-insecure-requests" not in headers
    assert "user-agent" not in headers


@pytest.mark.parametrize(
    ("follow_up", "expected"),
    [
        (None, "home"),
        ({"attachments": [], "backend_uuid": "backend-id"}, "followup"),
    ],
)
def test_sync_client_uses_browser_query_source(
    follow_up: dict[str, Any] | None, expected: str
) -> None:
    session = RecordingSyncSession()
    client = SyncClient.__new__(SyncClient)
    client.session = session
    client.own = True
    client.copilot = float("inf")
    client.file_upload = float("inf")
    client._user_info = {}

    stream = client.search(
        "query source probe",
        mode="pro",
        model="gpt-5.6-terra",
        follow_up=follow_up,
        stream=True,
    )
    list(stream)

    assert session.requests[0]["json"]["params"]["query_source"] == expected


def test_sync_client_uses_current_browser_ask_headers() -> None:
    assert DEFAULT_HEADERS["accept"] == "*/*"
    assert DEFAULT_HEADERS["sec-fetch-dest"] == "empty"
    assert DEFAULT_HEADERS["sec-fetch-mode"] == "cors"
    assert "sec-fetch-user" not in DEFAULT_HEADERS
    assert "upgrade-insecure-requests" not in DEFAULT_HEADERS
    assert "user-agent" not in DEFAULT_HEADERS

    session = RecordingSyncSession()
    client = SyncClient.__new__(SyncClient)
    client.session = session
    client.own = True
    client.copilot = float("inf")
    client.file_upload = float("inf")
    client._user_info = {
        "user": {
            "id": "account-id",
            "subscription_tier": "pro",
        }
    }

    stream = client.search(
        "request header probe",
        mode="pro",
        model="gpt-5.6-terra",
        stream=True,
        language="zh-CN",
    )
    list(stream)

    request = session.requests[0]
    params = request["json"]["params"]
    headers = request["headers"]

    assert request["url"] == ENDPOINT_SSE_ASK
    assert headers["accept"] == "text/event-stream"
    assert headers["content-type"] == "application/json"
    assert headers["sec-fetch-dest"] == "empty"
    assert headers["sec-fetch-mode"] == "cors"
    assert headers["x-pplx-account"] == "account-id"
    assert headers["x-request-id"] == params["frontend_uuid"]
    assert headers["x-perplexity-request-endpoint"] == ENDPOINT_SSE_ASK


def test_sync_client_omits_account_header_for_anonymous_requests() -> None:
    session = RecordingSyncSession()
    client = SyncClient.__new__(SyncClient)
    client.session = session
    client.own = False
    client.copilot = 0
    client.file_upload = 0
    client._user_info = {}

    stream = client.search("anonymous header probe", mode="auto", stream=True)
    list(stream)

    assert "x-pplx-account" not in session.requests[0]["headers"]


def test_every_published_catalog_model_uses_current_browser_ask_headers(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    snapshot = Path(__file__).parents[1] / "catalog" / "model_config_v2.json"
    config = json.loads(snapshot.read_text(encoding="utf-8"))
    registry = ModelRegistry(cache_path=tmp_path / "models.json")
    definitions = ModelRegistry._definitions_from_config(config)
    registry._definitions = definitions
    monkeypatch.setattr("perplexity.client.get_model_registry", lambda: registry)

    callable_definitions = [definition for definition in definitions if not definition.alias]
    assert callable_definitions

    for definition in callable_definitions:
        session = RecordingSyncSession()
        client = SyncClient.__new__(SyncClient)
        client.session = session
        client.own = True
        client.subscription_tier = "max"
        client.copilot = float("inf")
        client.file_upload = float("inf")
        client._user_info = {"user": {"id": "max-account"}}

        stream = client.search(
            "published model header probe",
            mode=definition.mode,
            model=definition.public_name,
            stream=True,
        )
        list(stream)

        request = session.requests[0]
        params = request["json"]["params"]
        headers = request["headers"]
        assert params["model_preference"] == definition.internal_id
        assert headers["accept"] == "text/event-stream"
        assert headers["sec-fetch-mode"] == "cors"
        assert headers["x-pplx-account"] == "max-account"
        assert headers["x-request-id"] == params["frontend_uuid"]
