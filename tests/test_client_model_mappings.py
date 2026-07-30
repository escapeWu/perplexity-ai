"""Verify the service client uses canonical model mappings and browser request metadata."""

from typing import Any

import pytest

from perplexity.client import Client as SyncClient
from perplexity.config import MODEL_MAPPINGS


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

    stream = client.search("model mapping probe", mode=mode, model=model, stream=True)
    list(stream)

    assert session.requests[0]["json"]["params"]["model_preference"] == slug


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

    stream = client.search(
        "query source probe",
        mode="pro",
        model="gpt-5.6-terra",
        follow_up=follow_up,
        stream=True,
    )
    list(stream)

    assert session.requests[0]["json"]["params"]["query_source"] == expected
