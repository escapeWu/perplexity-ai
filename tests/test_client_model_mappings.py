"""Verify every model uses canonical mappings and current browser request metadata."""

import json
import logging
from pathlib import Path
from typing import Any

import pytest

from perplexity.client import Client as SyncClient
from perplexity.config import (
    DEFAULT_HEADERS,
    ENDPOINT_SSE_ASK,
    ENDPOINT_UPLOAD_URL,
    MODEL_MAPPINGS,
)
from perplexity.model_registry import ModelRegistry


@pytest.fixture(autouse=True)
def static_model_registry(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    """Keep canonical mapping tests independent from a developer's live cache."""
    registry = ModelRegistry(cache_path=tmp_path / "missing-model-cache.json")
    monkeypatch.setattr("perplexity.client.get_model_registry", lambda: registry)


class RecordingSyncSession:
    def __init__(self, response: object | None = None) -> None:
        self.requests: list[dict[str, Any]] = []
        self.response = response or EmptySyncResponse()

    def post(self, url: str, **kwargs: Any) -> object:
        self.requests.append({"url": url, **kwargs})
        return self.response


class EmptySyncResponse:
    def iter_lines(self, delimiter: bytes):
        return iter(())

    def close(self) -> None:
        pass


class EventSyncResponse:
    def __init__(self, events: list[dict[str, Any]]) -> None:
        self.events = events

    def iter_lines(self, delimiter: bytes):
        del delimiter
        for event in self.events:
            yield f"event: message\r\ndata: {json.dumps(event)}".encode()

    def close(self) -> None:
        pass


class JsonResponse:
    def __init__(self, payload: dict[str, Any], ok: bool = True) -> None:
        self.payload = payload
        self.ok = ok

    def json(self) -> dict[str, Any]:
        return self.payload


class UploadRecordingSession:
    def __init__(self) -> None:
        self.requests: list[dict[str, Any]] = []

    def post(self, url: str, **kwargs: Any) -> object:
        self.requests.append({"url": url, **kwargs})
        if url == ENDPOINT_UPLOAD_URL:
            return JsonResponse(
                {
                    "fields": {},
                    "s3_bucket_url": "https://upload.example",
                    "s3_object_url": "https://cdn.example/new.txt",
                }
            )
        if url == "https://upload.example":
            return JsonResponse({})
        if url == ENDPOINT_SSE_ASK:
            return EventSyncResponse([{"backend_uuid": "backend-1", "answer": "ok"}])
        raise AssertionError(f"Unexpected URL: {url}")


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

    params = session.requests[0]["json"]["params"]
    assert params["query_source"] == expected
    assert params["last_backend_uuid"] == (follow_up["backend_uuid"] if follow_up else None)
    assert params["attachments"] == (follow_up["attachments"] if follow_up else [])


@pytest.mark.parametrize(
    "follow_up",
    [
        "backend-id",
        {},
        {"backend_uuid": "", "attachments": []},
        {"backend_uuid": "backend-id", "attachments": "not-a-list"},
        {"backend_uuid": "backend-id", "attachments": [123]},
    ],
)
def test_sync_client_rejects_invalid_follow_up(follow_up: Any) -> None:
    client = SyncClient.__new__(SyncClient)
    client.session = RecordingSyncSession()
    client.own = True
    client.copilot = float("inf")
    client.file_upload = float("inf")
    client._user_info = {}

    with pytest.raises(ValueError, match="follow_up"):
        client.search("invalid follow-up", mode="pro", follow_up=follow_up)


def test_sync_client_accumulates_new_and_prior_follow_up_attachments(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class DummyMime:
        def addpart(self, *args: Any, **kwargs: Any) -> None:
            pass

    monkeypatch.setattr("perplexity.client.CurlMime", DummyMime)
    session = UploadRecordingSession()
    client = SyncClient.__new__(SyncClient)
    client.session = session
    client.own = True
    client.copilot = float("inf")
    client.file_upload = float("inf")
    client._user_info = {}

    result = client.search(
        "continue with a new file",
        mode="pro",
        files={"new.txt": b"new file"},
        follow_up={
            "backend_uuid": "backend-0",
            "attachments": ["https://cdn.example/prior.txt"],
        },
    )

    ask_request = next(
        request for request in session.requests if request["url"] == ENDPOINT_SSE_ASK
    )
    assert ask_request["json"]["params"]["attachments"] == [
        "https://cdn.example/new.txt",
        "https://cdn.example/prior.txt",
    ]
    assert result["_follow_up"] == {
        "backend_uuid": "backend-1",
        "attachments": [
            "https://cdn.example/new.txt",
            "https://cdn.example/prior.txt",
        ],
    }


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


def test_sync_client_marks_and_logs_silent_model_downgrade(
    caplog: pytest.LogCaptureFixture,
) -> None:
    session = RecordingSyncSession(
        EventSyncResponse(
            [
                {
                    "display_model": "turbo",
                    "user_selected_model": "grok46medium",
                    "status": "COMPLETED",
                }
            ]
        )
    )
    client = SyncClient.__new__(SyncClient)
    client.session = session
    client.own = True
    client.subscription_tier = "pro"
    client.copilot = float("inf")
    client.file_upload = float("inf")
    client._user_info = {"user": {"id": "account-id"}}

    with caplog.at_level(logging.WARNING, logger="perplexity.client"):
        events = list(
            client.search(
                "downgrade probe",
                mode="reasoning",
                model="grok-4.6-thinking",
                stream=True,
            )
        )

    assert events == [
        {
            "display_model": "turbo",
            "user_selected_model": "grok46medium",
            "status": "COMPLETED",
            "model_downgraded": True,
            "requested_model": "grok46medium",
            "effective_model": "turbo",
        }
    ]
    assert "silently downgraded" in caplog.text


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
