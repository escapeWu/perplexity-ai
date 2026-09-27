"""Unavailable public model IDs use Best without hiding the actual execution model."""
import asyncio
import importlib
import json

import pytest

from perplexity.server import jobs, oai
from perplexity.server.utils import resolve_chat_model
from tests.conftest import request_for


@pytest.mark.parametrize(
    "requested,thinking,effective,mode",
    [("retired-model", False, "perplexity-search", "pro"),
     ("retired-model", True, "perplexity-thinking", "reasoning"),
     ("retired-model-thinking", False, "perplexity-thinking", "reasoning")],
)
def test_fallback_uses_best_and_preserves_thinking(requested, thinking, effective, mode):
    assert resolve_chat_model(requested, thinking, {"pro"}) == {
        "mode": mode, "model": None, "model_id": effective, "requested_model": requested,
    }


@pytest.mark.parametrize("model", ["perplexity-search", "perplexity-thinking", "perplexity-deepsearch"])
def test_valid_models_do_not_get_fallback_metadata(model):
    resolved = resolve_chat_model(model, subscription_tiers={"pro"})
    assert resolved["model_id"] == model
    assert "requested_model" not in resolved


@pytest.mark.parametrize("model,thinking", [(None, False), (1, False), ("", False),
    (" ", False), ({}, False), ("retired-model", "true"), ("perplexity-deepsearch", True)])
def test_fallback_does_not_swallow_invalid_inputs(model, thinking):
    with pytest.raises(ValueError):
        resolve_chat_model(model, thinking, {"pro"})


@pytest.mark.asyncio
@pytest.mark.parametrize("stream", [False, True])
async def test_completion_notice_is_visible_once_and_saved_in_history(api_runtime, stream):
    source = api_runtime.test_upstream
    request = {"model": "retired-model", "stream": stream,
               "messages": [{"role": "user", "content": "hello"}]}
    if not stream:
        source.release["[User]: hello"].set()
    response = await oai.oai_chat_completions(request_for("/v1/chat/completions", request))
    assert response.status_code == 200
    if stream:
        iterator = response.body_iterator
        first = json.loads((await asyncio.wait_for(anext(iterator), 2)).removeprefix("data: "))
        assert "模型路由提示" not in first["choices"][0]["delta"]["content"]
        source.release["[User]: hello"].set()
        frames = [part async for part in iterator]
        assert frames[-1] == "data: [DONE]\n\n"
        chunks = [first] + [json.loads(part.removeprefix("data: "))
                            for part in frames if part.startswith("data: {")]
        data = chunks[-1]
        answer = "".join(chunk["choices"][0]["delta"].get("content", "") for chunk in chunks)
        assert data["choices"][0]["finish_reason"] == "stop"
    else:
        data = json.loads(response.body)
        answer = data["choices"][0]["message"]["content"]
    assert data["model"] == "perplexity-search"
    assert data["model_fallback"]["requested_model"] == "retired-model"
    assert data["model_fallback"]["effective_model"] == data["model"]
    assert answer.startswith("[User]: hello partial complete\n\n")
    assert answer.count("[模型路由提示]") == 1
    assert answer.endswith(data["model_fallback"]["message"])
    assert "模型使用错误" in answer and "已自动路由到 Best" in answer
    assert api_runtime.sessions.get_messages(data["session_id"])[-1]["content"] == answer
    assert source.calls[0]["mode"] == "pro" and source.calls[0]["model"] is None
    final = await api_runtime.get(data["job_id"])
    assert final["payload"]["requested_model"] == "retired-model"
    assert final["snapshot"]["answer"] == answer


@pytest.mark.asyncio
async def test_jobs_keep_fallback_identity_during_idempotent_replay(api_runtime):
    body = {"model": "retired-model", "thinking": True,
            "messages": [{"role": "user", "content": "fallback task"}]}
    headers = [(b"idempotency-key", b"fallback-test")]
    accepted = await jobs.jobs(request_for("/v1/jobs", body, headers=headers))
    assert accepted.status_code == 202
    data = json.loads(accepted.body)
    assert data["model"] == "perplexity-thinking"
    replay = await jobs.jobs(request_for("/v1/jobs", body, headers=headers))
    assert json.loads(replay.body)["job_id"] == data["job_id"]
    conflict = await jobs.jobs(request_for("/v1/jobs", {**body, "model": "another-invalid-model"}, headers=headers))
    assert conflict.status_code == 409
    assert json.loads(conflict.body)["error"]["type"] == "idempotency_conflict"
    api_runtime.test_upstream.release["fallback task"].set()
    await asyncio.wait_for(api_runtime.wait(data["job_id"]), 2)
    response = await jobs.job_result(request_for("/result", method="GET", params={"job_id": data["job_id"]}))
    result = json.loads(response.body)["result"]
    assert "Best Thinking" in result["answer"]
    assert result["model_fallback"]["effective_model"] == "perplexity-thinking"
    repeated = await jobs.jobs(request_for("/v1/jobs", body, headers=headers))
    assert json.loads(repeated.body)["job_id"] == data["job_id"]
    assert len(api_runtime.test_upstream.calls) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("detached", [False, True])
async def test_mcp_fallback_returns_the_same_visible_notice(api_runtime, detached):
    tools = importlib.import_module("perplexity.server.mcp")
    api_runtime.test_upstream.release["mcp fallback"].set()
    if detached:
        accepted = await tools.perplexity_task_submit.fn("mcp fallback", model="retired-model")
        assert accepted["status"] == "ok"
        await asyncio.wait_for(api_runtime.wait(accepted["job_id"]), 2)
        response = await tools.perplexity_task_status.fn(accepted["job_id"])
        result = response["snapshot"]
    else:
        response = await tools.perplexity_ask_v2.fn("mcp fallback", model="retired-model")
        assert response["status"] == "ok"
        result = response["data"]
    assert response["model"] == "perplexity-search"
    assert result["answer"].count("[模型路由提示]") == 1
    assert result["model_fallback"]["requested_model"] == "retired-model"


@pytest.mark.asyncio
async def test_upstream_failure_is_not_masked_by_a_fallback_notice(api_runtime):
    api_runtime.test_upstream.release["empty response"].set()
    accepted = await jobs.jobs(request_for("/v1/jobs", {"model": "retired-model",
        "messages": [{"role": "user", "content": "empty response"}]}))
    job_id = json.loads(accepted.body)["job_id"]
    final = await asyncio.wait_for(api_runtime.wait(job_id), 2)
    assert final["state"] == "failed"
    assert final["error"]["code"] == "empty_answer"
    assert "model_fallback" not in final["snapshot"]
    assert "模型路由提示" not in final["snapshot"].get("answer", "")
    assert api_runtime.sessions.get_messages(final["session_id"]) == []
