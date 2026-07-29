"""Unit tests for true OpenAI-compatible SSE forwarding."""

import asyncio
import json
import threading
from unittest.mock import AsyncMock, patch

import pytest
from starlette.requests import Request
from starlette.responses import JSONResponse, StreamingResponse

from perplexity.server import oai


def make_request(payload):
    body = json.dumps(payload).encode()
    delivered = False

    async def receive():
        nonlocal delivered
        if delivered:
            return {"type": "http.disconnect"}
        delivered = True
        return {"type": "http.request", "body": body, "more_body": False}

    scope = {
        "type": "http",
        "method": "POST",
        "path": "/v1/chat/completions",
        "headers": [(b"authorization", f"Bearer {oai.MCP_TOKEN}".encode())],
    }
    return Request(scope, receive)


def decode_sse(data):
    assert data.startswith("data: ")
    return json.loads(data[6:])


@pytest.mark.asyncio
async def test_stream_forwards_first_snapshot_before_upstream_finishes():
    release_upstream = threading.Event()
    upstream_closed = threading.Event()

    def upstream():
        try:
            yield {"answer": "Hel"}
            release_upstream.wait(timeout=2)
            yield {
                "answer": "Hello",
                "chunks": [{"url": "https://example.com", "title": "Example"}],
            }
        finally:
            upstream_closed.set()

    with patch("perplexity.server.oai.run_query_stream", return_value=upstream()):
        response = await oai._stream_chat_response(
            "test", "auto", None, "perplexity-search", "chatcmpl-test", 1
        )
        assert response.headers["x-accel-buffering"] == "no"
        iterator = response.body_iterator

        first = await asyncio.wait_for(anext(iterator), timeout=0.5)
        assert decode_sse(first)["choices"][0]["delta"]["content"] == "Hel"
        assert release_upstream.is_set() is False

        release_upstream.set()
        second = await asyncio.wait_for(anext(iterator), timeout=0.5)
        final = await asyncio.wait_for(anext(iterator), timeout=0.5)
        done = await asyncio.wait_for(anext(iterator), timeout=0.5)

    assert decode_sse(second)["choices"][0]["delta"]["content"] == "lo"
    final_data = decode_sse(final)
    assert final_data["choices"][0]["finish_reason"] == "stop"
    assert final_data["sources"] == [{"url": "https://example.com", "title": "Example"}]
    assert done == "data: [DONE]\n\n"
    assert upstream_closed.wait(timeout=1)


@pytest.mark.asyncio
async def test_downstream_close_closes_upstream_iterator():
    upstream_closed = threading.Event()

    def upstream():
        try:
            yield {"answer": "partial"}
            yield {"answer": "unused"}
        finally:
            upstream_closed.set()

    with patch("perplexity.server.oai.run_query_stream", return_value=upstream()):
        response = await oai._stream_chat_response(
            "test", "auto", None, "perplexity-search", "chatcmpl-test", 1
        )
        iterator = response.body_iterator
        await anext(iterator)
        await iterator.aclose()

    assert upstream_closed.wait(timeout=1)


@pytest.mark.asyncio
async def test_chat_completions_streams_by_default():
    streamed_response = StreamingResponse(iter(["stream"]))
    stream_mock = AsyncMock(return_value=streamed_response)
    non_stream_mock = AsyncMock(return_value=JSONResponse({"unexpected": True}))

    with (
        patch("perplexity.server.oai._stream_chat_response", stream_mock),
        patch("perplexity.server.oai._non_stream_chat_response", non_stream_mock),
    ):
        response = await oai.oai_chat_completions(
            make_request(
                {
                    "model": "perplexity-search",
                    "messages": [{"role": "user", "content": "hello"}],
                }
            )
        )

    assert response is streamed_response
    stream_mock.assert_awaited_once()
    non_stream_mock.assert_not_awaited()


@pytest.mark.asyncio
async def test_chat_completions_stream_false_returns_complete_json():
    streamed_response = StreamingResponse(iter(["unexpected"]))
    complete_response = JSONResponse({"object": "chat.completion"})
    stream_mock = AsyncMock(return_value=streamed_response)
    non_stream_mock = AsyncMock(return_value=complete_response)

    with (
        patch("perplexity.server.oai._stream_chat_response", stream_mock),
        patch("perplexity.server.oai._non_stream_chat_response", non_stream_mock),
    ):
        response = await oai.oai_chat_completions(
            make_request(
                {
                    "model": "perplexity-search",
                    "messages": [{"role": "user", "content": "hello"}],
                    "stream": False,
                }
            )
        )

    assert response is complete_response
    non_stream_mock.assert_awaited_once()
    stream_mock.assert_not_awaited()
