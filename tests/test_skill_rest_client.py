"""Contract tests for the skill's MCP-shaped REST client."""

import importlib.util
import sys
from pathlib import Path


CLIENT_PATH = (
    Path(__file__).parents[1] / ".agents" / "skills" / "perplexity-search" / "scripts" / "client.py"
)
SPEC = importlib.util.spec_from_file_location("perplexity_skill_client", CLIENT_PATH)
client_module = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = client_module
SPEC.loader.exec_module(client_module)
PerplexityRestClient = client_module.PerplexityRestClient


def test_ask_v2_maps_rest_completion_to_mcp_shape(tmp_path):
    attachment = tmp_path / "notes.txt"
    attachment.write_text("evidence")
    client = PerplexityRestClient("http://localhost:8000", "token")
    captured = {}

    def request(method, path, **kwargs):
        captured.update(method=method, path=path, **kwargs)
        return {
            "job_id": "job_1",
            "session_id": "sess_1",
            "model": "gpt-5-6-terra-thinking",
            "choices": [{"message": {"content": "answer"}}],
            "sources": [{"url": "https://example.com"}],
        }

    client._request_json = request
    result = client.perplexity_ask_v2(
        "question",
        model="gpt-5-6-terra",
        thinking=True,
        files=[attachment],
    )

    assert result == {
        "status": "ok",
        "session_id": "sess_1",
        "job_id": "job_1",
        "model": "gpt-5-6-terra-thinking",
        "data": {
            "answer": "answer",
            "sources": [{"url": "https://example.com"}],
        },
    }
    assert captured["method"] == "POST"
    assert captured["path"] == "chat/completions"
    assert captured["payload"]["thinking"] is True
    content = captured["payload"]["messages"][0]["content"]
    assert content[1]["filename"] == "notes.txt"
    assert content[1]["file_data"].startswith("data:application/octet-stream;base64,")


def test_task_methods_keep_mcp_names_and_shapes():
    client = PerplexityRestClient("http://localhost:8000/v1", "token")
    responses = iter(
        [
            {"id": "job_1", "job_id": "job_1", "session_id": "sess_1", "state": "queued"},
            {
                "id": "job_1",
                "job_id": "job_1",
                "session_id": "sess_1",
                "state": "completed",
                "result": {"answer": "done", "sources": []},
            },
            {"id": "job_1", "job_id": "job_1", "session_id": "sess_1", "state": "completed"},
        ]
    )
    calls = []

    def request(method, path, **kwargs):
        calls.append((method, path, kwargs))
        return next(responses)

    client._request_json = request
    submitted = client.perplexity_task_submit("question", idempotency_key="request-1")
    status = client.perplexity_task_status("job_1", wait_seconds=20)
    cancelled = client.perplexity_task_cancel("job_1")

    assert submitted["status"] == "ok" and submitted["state"] == "queued"
    assert status["status"] == "ok"
    assert status["snapshot"] == {"answer": "done", "sources": []}
    assert cancelled["status"] == "ok" and cancelled["state"] == "completed"
    assert calls[0][2]["headers"] == {"Idempotency-Key": "request-1"}
    assert calls[1][1] == "jobs/job_1/result"
    assert calls[2][1] == "jobs/job_1/cancel"


def test_cli_uses_mcp_tool_names():
    parser = client_module.build_parser()
    assert parser.parse_args(["perplexity_ask_v2", "question"]).command == "perplexity_ask_v2"
    assert (
        parser.parse_args(["perplexity_research_v2", "topic"]).command == "perplexity_research_v2"
    )
    assert (
        parser.parse_args(["perplexity_task_status", "job_1"]).command == "perplexity_task_status"
    )
