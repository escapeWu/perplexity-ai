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
    assert all("perplexity_progress" not in decode_sse(item) for item in (first, second, final))
    assert upstream_closed.wait(timeout=1)


@pytest.mark.asyncio
async def test_stream_progress_extension_emits_deduplicated_lifecycle_events():
    steps = [
        {
            "step_type": "INITIAL_QUERY",
            "content": {"goal_id": "internal-goal", "query": "private query"},
        }
    ]

    def upstream():
        yield {"text": list(steps)}
        steps.append(
            {
                "step_type": "SEARCH_WEB",
                "content": {
                    "goal_id": "internal-goal",
                    "queries": ["weather Seoul", "weather Tokyo"],
                },
            }
        )
        yield {"text": list(steps)}
        steps.append(
            {
                "step_type": "SEARCH_RESULTS",
                "content": {
                    "goal_id": "internal-goal",
                    "web_results": [{"url": "https://a.test"}, {"url": "https://b.test"}],
                },
            }
        )
        yield {"text": list(steps)}
        steps.append(
            {
                "step_type": "FINAL",
                "content": {"goal_id": "internal-goal"},
            }
        )
        yield {"text": list(steps), "answer": "Hel"}
        yield {"text": list(steps), "answer": "Hello"}

    with patch("perplexity.server.oai.run_query_stream", return_value=upstream()):
        response = await oai._stream_chat_response(
            "test",
            "pro",
            "gpt-5.6-terra",
            "perplexity-search",
            "chatcmpl-test",
            1,
            include_progress=True,
        )
        frames = [frame async for frame in response.body_iterator]

    payloads = [decode_sse(frame) for frame in frames if frame != "data: [DONE]\n\n"]
    progress = [
        payload["perplexity_progress"]
        for payload in payloads
        if "perplexity_progress" in payload
    ]

    assert [(event["stage"], event["status"]) for event in progress] == [
        ("initial_query", "running"),
        ("initial_query", "completed"),
        ("search_web", "running"),
        ("search_web", "completed"),
        ("search_results", "running"),
        ("search_results", "completed"),
        ("final", "running"),
        ("final", "completed"),
    ]
    assert progress[2]["detail"] == {
        "queries": ["weather Seoul", "weather Tokyo"],
        "query_count": 2,
    }
    assert progress[4]["detail"] == {"source_count": 2}
    assert "goal_id" not in json.dumps(progress)

    content_deltas = [
        payload["choices"][0]["delta"]["content"]
        for payload in payloads
        if payload["choices"][0]["delta"].get("content")
    ]
    assert content_deltas == ["Hel", "lo"]
    assert payloads[-1]["choices"][0]["finish_reason"] == "stop"
    assert frames[-1] == "data: [DONE]\n\n"


@pytest.mark.asyncio
async def test_stream_progress_starts_before_first_upstream_event():
    upstream_started = threading.Event()

    def upstream():
        upstream_started.set()
        yield {"answer": "Hello"}

    with patch("perplexity.server.oai.run_query_stream", return_value=upstream()):
        response = await oai._stream_chat_response(
            "test",
            "pro",
            None,
            "perplexity-search",
            "chatcmpl-test",
            1,
            include_progress=True,
        )
        iterator = response.body_iterator
        first = await asyncio.wait_for(anext(iterator), timeout=0.5)
        assert upstream_started.is_set() is False
        await iterator.aclose()

    first_payload = decode_sse(first)
    assert first_payload["perplexity_progress"]["stage"] == "initial_query"
    assert first_payload["perplexity_progress"]["status"] == "running"


@pytest.mark.asyncio
async def test_stream_progress_marks_active_stage_failed_on_upstream_error():
    def upstream():
        yield {
            "text": [
                {
                    "step_type": "SEARCH_WEB",
                    "content": {"queries": ["test query"]},
                }
            ]
        }
        raise RuntimeError("upstream interrupted")

    with patch("perplexity.server.oai.run_query_stream", return_value=upstream()):
        response = await oai._stream_chat_response(
            "test",
            "pro",
            None,
            "perplexity-search",
            "chatcmpl-test",
            1,
            include_progress=True,
        )
        frames = [frame async for frame in response.body_iterator]

    payloads = [decode_sse(frame) for frame in frames if frame != "data: [DONE]\n\n"]
    progress = [
        payload["perplexity_progress"]
        for payload in payloads
        if "perplexity_progress" in payload
    ]
    assert [(event["stage"], event["status"]) for event in progress] == [
        ("initial_query", "running"),
        ("initial_query", "completed"),
        ("search_web", "running"),
        ("search_web", "failed"),
    ]
    assert payloads[-1]["choices"][0]["finish_reason"] == "error"
    assert payloads[-1]["error"]["message"] == "upstream interrupted"


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
    assert stream_mock.await_args.kwargs["include_progress"] is False
    non_stream_mock.assert_not_awaited()


@pytest.mark.asyncio
async def test_chat_completions_enables_progress_extension_on_request():
    streamed_response = StreamingResponse(iter(["stream"]))
    stream_mock = AsyncMock(return_value=streamed_response)

    with patch("perplexity.server.oai._stream_chat_response", stream_mock):
        response = await oai.oai_chat_completions(
            make_request(
                {
                    "model": "perplexity-search",
                    "messages": [{"role": "user", "content": "hello"}],
                    "perplexity": {"include_progress": True},
                }
            )
        )

    assert response is streamed_response
    assert stream_mock.await_args.kwargs["include_progress"] is True


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
