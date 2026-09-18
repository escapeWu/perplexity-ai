"""Compatibility HTTP tests against the real task runner and durable session store."""
import asyncio
import json

import pytest
from starlette.responses import StreamingResponse

from perplexity.server import oai
from perplexity.upstream_protocol import UpstreamError
from tests.conftest import request_for


def payload(text="hello", **kwargs):
    return {"model": "perplexity-search", "messages": [{"role": "user", "content": text}], **kwargs}


def frames(response):
    return response.body_iterator


def decode(frame):
    return json.loads(frame.removeprefix("data: "))


@pytest.mark.asyncio
async def test_stream_forwards_first_snapshot_before_upstream_finishes(api_runtime):
    source = api_runtime.test_upstream
    response = await oai._stream_chat_response("hello", "auto", None, "perplexity-search", "chatcmpl-test", 1)
    iterator = frames(response)
    first = decode(await asyncio.wait_for(anext(iterator), 1))
    assert first["choices"][0]["delta"]["content"] == "hello partial"
    assert not source.release["hello"].is_set()
    source.release["hello"].set()
    remaining = [frame async for frame in iterator]
    assert decode(remaining[-2])["choices"][0]["finish_reason"] == "stop"
    assert remaining[-1] == "data: [DONE]\n\n"
    assert len(source.calls) == 1


@pytest.mark.asyncio
async def test_initial_progress_precedes_upstream_and_failure_settles_it(api_runtime):
    gate = asyncio.Event()
    async def failing(client, **kwargs):
        await gate.wait()
        raise UpstreamError("upstream failed", "upstream_http_error")
        yield {}
    api_runtime.transport = failing
    response = await oai._stream_chat_response("hello", "auto", None, "perplexity-search", "id", 1, include_progress=True)
    iterator = frames(response)
    first = decode(await asyncio.wait_for(anext(iterator), 1))
    assert first["perplexity_progress"]["status"] == "running"
    gate.set()
    rest = [decode(item) async for item in iterator if item.startswith("data: {")]
    assert any(p.get("perplexity_progress", {}).get("status") == "failed" for p in rest)
    assert rest[-1]["error"]["type"] == "upstream_http_error"
    assert not any(p["choices"][0]["finish_reason"] == "stop" for p in rest)


@pytest.mark.asyncio
async def test_downstream_close_stops_request_owned_job(api_runtime):
    response = await oai._stream_chat_response("hello", "auto", None, "perplexity-search", "id", 1)
    await anext(response.body_iterator)
    await response.body_iterator.aclose()
    final = await asyncio.wait_for(api_runtime.wait(response.headers["x-job-id"]), 2)
    assert final["state"] == "cancelled"
    assert api_runtime.sessions.get_messages(final["session_id"]) == []
    assert api_runtime.test_upstream.closed["hello"].is_set()
    assert not api_runtime.observers


@pytest.mark.asyncio
async def test_chat_completions_streams_by_default(api_runtime):
    api_runtime.test_upstream.release["[User]: hello"].set()
    response = await oai.oai_chat_completions(request_for("/v1/chat/completions", payload()))
    assert isinstance(response, StreamingResponse)
    assert response.headers["x-session-id"].startswith("sess_")
    content = [item async for item in response.body_iterator]
    assert content[-1] == "data: [DONE]\n\n"


@pytest.mark.asyncio
async def test_complete_json_and_native_follow_up(api_runtime):
    source = api_runtime.test_upstream
    source.release["[User]: first"].set()
    response = await oai.oai_chat_completions(request_for("/v1/chat/completions", payload("first", stream=False)))
    assert response.status_code == 200
    first = json.loads(response.body)
    assert first["choices"][0]["message"]["content"] == "[User]: first partial complete"
    source.release["second"].set()
    second = await oai.oai_chat_completions(request_for("/v1/chat/completions", payload("second", stream=False, session_id=first["session_id"])))
    assert second.status_code == 200
    assert source.calls[-1]["query"] == "second"
    assert source.calls[-1]["follow_up"]["backend_uuid"] == "backend-[User]: first"
    assert len(api_runtime.sessions.get_messages(first["session_id"])) == 4


@pytest.mark.asyncio
async def test_thinking_flag_selects_and_persists_effective_model(api_runtime):
    api_runtime.test_upstream.release["[User]: hello"].set()
    response = await oai.oai_chat_completions(request_for("/v1/chat/completions",
        payload(model="gpt-5-6-terra", thinking=True, stream=False)))
    data = json.loads(response.body)
    assert response.status_code == 200
    assert data["model"] == "gpt-5-6-terra-thinking"
    assert api_runtime.test_upstream.calls[-1]["model"] == "gpt-5.6-terra-thinking"
    assert api_runtime.sessions.get_session(data["session_id"]).model == data["model"]


@pytest.mark.asyncio
@pytest.mark.parametrize("options,status", [({"thinking": "yes"}, 400), ({"reasoning_effort": "high"}, 400),
    ({"session_id": "sess_" + "0" * 32}, 404), ({"stream": 1}, 400), ({"model": "missing-model"}, 400)])
async def test_invalid_requests_never_start_upstream(api_runtime, options, status):
    response = await oai.oai_chat_completions(request_for("/v1/chat/completions", payload(**options)))
    assert response.status_code == status
    assert not api_runtime.test_upstream.calls


@pytest.mark.asyncio
async def test_answer_rewrite_is_not_concatenated_in_oai_stream(api_runtime):
    gate = asyncio.Event()
    async def revised(client, **kwargs):
        yield {"answer": "draft", "_follow_up": {"backend_uuid": "backend", "attachments": []}}
        await gate.wait()
        yield {"answer": "revised", "status": "COMPLETED", "_follow_up": {"backend_uuid": "backend", "attachments": []}}
    api_runtime.transport = revised
    response = await oai._stream_chat_response("hello", "auto", None, "perplexity-search", "id", 1)
    first = decode(await anext(response.body_iterator))
    assert first["choices"][0]["delta"]["content"] == "draft"
    gate.set()
    rest = [decode(item) async for item in response.body_iterator if item.startswith("data: {")]
    assert rest[-1]["error"]["type"] == "answer_revised"
    assert not any(item["choices"][0]["delta"].get("content") for item in rest)


@pytest.mark.asyncio
async def test_nonstream_disconnect_cancels_request_owned_task(api_runtime):
    disconnected = asyncio.Event()
    call = asyncio.create_task(oai.oai_chat_completions(request_for("/v1/chat/completions", payload(stream=False), disconnect=disconnected)))
    await asyncio.wait_for(api_runtime.test_upstream.started["[User]: hello"].wait(), 1)
    disconnected.set()
    response = await asyncio.wait_for(call, 2)
    assert response.status_code == 499
    jobs = api_runtime.store.list()
    final = await api_runtime.wait(jobs[0]["id"])
    assert final["state"] == "cancelled"
