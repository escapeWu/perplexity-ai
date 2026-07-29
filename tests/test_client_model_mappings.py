"""Verify both clients use the canonical model mapping in request payloads."""

from typing import Any

import pytest

from perplexity.client import Client as SyncClient
from perplexity.config import MODEL_MAPPINGS
from perplexity_async.client import Client as AsyncClient


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


class RecordingAsyncSession:
    def __init__(self) -> None:
        self.requests: list[dict[str, Any]] = []

    async def post(self, url: str, **kwargs: Any) -> object:
        self.requests.append({"url": url, **kwargs})
        return object()


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


@pytest.mark.asyncio
@pytest.mark.parametrize(("mode", "model", "slug"), MODEL_CASES)
async def test_async_client_uses_canonical_model_mapping(
    mode: str, model: str | None, slug: str
) -> None:
    session = RecordingAsyncSession()
    client = AsyncClient.__new__(AsyncClient)
    client.session = session
    client.own = True
    client.copilot = float("inf")
    client.file_upload = float("inf")

    await client.search("model mapping probe", mode=mode, model=model, stream=True)

    assert session.requests[0]["json"]["params"]["model_preference"] == slug
