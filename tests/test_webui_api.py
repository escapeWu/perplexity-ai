import asyncio
import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from starlette.requests import Request

from perplexity.server import webui
from perplexity.server.webui_sessions import WebUISessionStore


def make_request(
    method: str,
    path: str,
    payload=None,
    *,
    token: str | None = None,
    path_params=None,
) -> Request:
    body = json.dumps(payload).encode() if payload is not None else b""
    delivered = False

    async def receive():
        nonlocal delivered
        if delivered:
            return {"type": "http.disconnect"}
        delivered = True
        return {"type": "http.request", "body": body, "more_body": False}

    headers = []
    if token is not None:
        headers.append((b"authorization", f"Bearer {token}".encode()))
    scope = {
        "type": "http",
        "method": method,
        "path": path,
        "headers": headers,
        "path_params": path_params or {},
    }
    return Request(scope, receive)


def response_json(response):
    return json.loads(response.body)


def make_store(tmp_path: Path) -> WebUISessionStore:
    return WebUISessionStore(tmp_path / "webui.sqlite3")


def make_pool(client_id="account-a"):
    pool = MagicMock()
    pool.clients = {client_id: object()}
    pool.get_client.return_value = (client_id, object())
    pool.get_client_state.return_value = "normal"
    pool.get_model_subscription_tiers.return_value = {"pro"}
    return pool


@pytest.mark.asyncio
async def test_session_crud_routes_and_authentication(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    unauthorized = await webui.webui_sessions(make_request("GET", "/v1/webui/sessions"))
    assert unauthorized.status_code == 401

    with patch("perplexity.server.webui.get_webui_session_store", return_value=store):
        created_response = await webui.webui_sessions(
            make_request(
                "POST",
                "/v1/webui/sessions",
                {"title": "Native thread"},
                token=webui._verify_auth.__globals__["MCP_TOKEN"],
            )
        )
        created = response_json(created_response)
        assert created_response.status_code == 201
        assert created["title"] == "Native thread"
        assert created["bound_client_id"] is None

        detail_response = await webui.webui_session_detail(
            make_request(
                "GET",
                f"/v1/webui/sessions/{created['id']}",
                token=webui._verify_auth.__globals__["MCP_TOKEN"],
                path_params={"session_id": created["id"]},
            )
        )
        assert response_json(detail_response)["messages"] == []

        renamed_response = await webui.webui_session_detail(
            make_request(
                "PATCH",
                f"/v1/webui/sessions/{created['id']}",
                {"title": "Renamed"},
                token=webui._verify_auth.__globals__["MCP_TOKEN"],
                path_params={"session_id": created["id"]},
            )
        )
        assert response_json(renamed_response)["title"] == "Renamed"

        listed_response = await webui.webui_sessions(
            make_request(
                "GET",
                "/v1/webui/sessions",
                token=webui._verify_auth.__globals__["MCP_TOKEN"],
            )
        )
        assert [item["id"] for item in response_json(listed_response)["data"]] == [created["id"]]

        deleted_response = await webui.webui_session_detail(
            make_request(
                "DELETE",
                f"/v1/webui/sessions/{created['id']}",
                token=webui._verify_auth.__globals__["MCP_TOKEN"],
                path_params={"session_id": created["id"]},
            )
        )
        assert response_json(deleted_response) == {"id": created["id"], "deleted": True}


@pytest.mark.asyncio
async def test_non_stream_first_turn_binds_and_commits_then_follow_up_reuses_cursor(
    tmp_path: Path,
) -> None:
    store = make_store(tmp_path)
    session = store.create_session()
    pool = make_pool()
    responses = [
        {
            "status": "ok",
            "data": {
                "answer": "First answer",
                "sources": [],
                "_follow_up": {"backend_uuid": "backend-1", "attachments": ["file-1"]},
            },
        },
        {
            "status": "ok",
            "data": {
                "answer": "Second answer",
                "sources": [],
                "_follow_up": {"backend_uuid": "backend-2", "attachments": ["file-1"]},
            },
        },
    ]

    with (
        patch("perplexity.server.webui.get_webui_session_store", return_value=store),
        patch("perplexity.server.webui.get_pool", return_value=pool),
        patch("perplexity.server.webui.run_query", side_effect=responses) as run,
    ):
        for text in ("First question", "Second question"):
            response = await webui.webui_chat_completions(
                make_request(
                    "POST",
                    "/v1/webui/chat/completions",
                    {
                        "session_id": session.id,
                        "model": "perplexity-search",
                        "messages": [{"role": "user", "content": text}],
                        "stream": False,
                    },
                    token=webui._verify_auth.__globals__["MCP_TOKEN"],
                )
            )
            assert response.status_code == 200

    assert store.get_session(session.id).client_id == "account-a"
    assert store.get_session(session.id).backend_uuid == "backend-2"
    assert [message["content"] for message in store.get_messages(session.id)] == [
        "First question",
        "First answer",
        "Second question",
        "Second answer",
    ]
    assert run.call_args_list[0].args[0] == "First question"
    assert run.call_args_list[0].args[9] is None
    assert run.call_args_list[1].args[0] == "Second question"
    assert run.call_args_list[1].args[9] == {
        "backend_uuid": "backend-1",
        "attachments": ["file-1"],
    }
    assert all(call.args[8] == "account-a" for call in run.call_args_list)
    assert pool.get_client.call_count == 1


@pytest.mark.asyncio
async def test_first_turn_failure_keeps_binding_and_missing_cursor_does_not_commit(
    tmp_path: Path,
) -> None:
    store = make_store(tmp_path)
    failed_session = store.create_session()
    missing_cursor_session = store.create_session()
    pool = make_pool()

    with (
        patch("perplexity.server.webui.get_webui_session_store", return_value=store),
        patch("perplexity.server.webui.get_pool", return_value=pool),
        patch(
            "perplexity.server.webui.run_query",
            return_value={"status": "error", "error_type": "RuntimeError", "message": "boom"},
        ),
    ):
        failed = await webui.webui_chat_completions(
            make_request(
                "POST",
                "/v1/webui/chat/completions",
                {
                    "session_id": failed_session.id,
                    "model": "perplexity-search",
                    "messages": [{"role": "user", "content": "question"}],
                    "stream": False,
                },
                token=webui._verify_auth.__globals__["MCP_TOKEN"],
            )
        )
    assert failed.status_code == 502
    assert store.get_session(failed_session.id).client_id == "account-a"
    assert store.get_messages(failed_session.id) == []

    with (
        patch("perplexity.server.webui.get_webui_session_store", return_value=store),
        patch("perplexity.server.webui.get_pool", return_value=pool),
        patch(
            "perplexity.server.webui.run_query",
            return_value={"status": "ok", "data": {"answer": "orphan", "sources": []}},
        ),
    ):
        missing_cursor = await webui.webui_chat_completions(
            make_request(
                "POST",
                "/v1/webui/chat/completions",
                {
                    "session_id": missing_cursor_session.id,
                    "model": "perplexity-search",
                    "messages": [{"role": "user", "content": "question"}],
                    "stream": False,
                },
                token=webui._verify_auth.__globals__["MCP_TOKEN"],
            )
        )
    assert missing_cursor.status_code == 502
    assert store.get_messages(missing_cursor_session.id) == []


@pytest.mark.asyncio
async def test_stream_commits_only_after_cursor_and_reports_session(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    session = store.create_session()
    pool = make_pool()

    def upstream():
        yield {"answer": "Hel"}
        yield {
            "answer": "Hello",
            "chunks": [{"url": "https://example.com", "title": "Source"}],
            "_follow_up": {"backend_uuid": "backend-1", "attachments": []},
        }

    with (
        patch("perplexity.server.webui.get_webui_session_store", return_value=store),
        patch("perplexity.server.webui.get_pool", return_value=pool),
        patch("perplexity.server.webui.run_query_stream", return_value=upstream()),
    ):
        response = await webui.webui_chat_completions(
            make_request(
                "POST",
                "/v1/webui/chat/completions",
                {
                    "session_id": session.id,
                    "model": "perplexity-search",
                    "messages": [{"role": "user", "content": "question"}],
                    "stream": True,
                },
                token=webui._verify_auth.__globals__["MCP_TOKEN"],
            )
        )
        frames = [frame async for frame in response.body_iterator]

    payloads = [json.loads(frame[6:]) for frame in frames if frame != "data: [DONE]\n\n"]
    assert [
        payload["choices"][0]["delta"].get("content")
        for payload in payloads
        if payload["choices"][0]["delta"].get("content")
    ] == ["Hel", "lo"]
    assert payloads[-1]["webui_session"]["bound_client_id"] == "account-a"
    assert store.get_session(session.id).backend_uuid == "backend-1"
    assert store.get_messages(session.id)[1]["content"] == "Hello"


@pytest.mark.asyncio
async def test_cancelled_stream_does_not_commit_turn(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    session = store.create_session()
    pool = make_pool()
    release = asyncio.Event()

    def upstream():
        yield {"answer": "Partial"}
        release.wait()
        yield {
            "answer": "Complete",
            "_follow_up": {"backend_uuid": "backend-1", "attachments": []},
        }

    # A generator that remains open after its first event models a disconnected browser.
    iterator = iter([{"answer": "Partial"}, {"answer": "Complete"}])
    with (
        patch("perplexity.server.webui.get_webui_session_store", return_value=store),
        patch("perplexity.server.webui.get_pool", return_value=pool),
        patch("perplexity.server.webui.run_query_stream", return_value=iterator),
    ):
        response = await webui.webui_chat_completions(
            make_request(
                "POST",
                "/v1/webui/chat/completions",
                {
                    "session_id": session.id,
                    "model": "perplexity-search",
                    "messages": [{"role": "user", "content": "question"}],
                    "stream": True,
                },
                token=webui._verify_auth.__globals__["MCP_TOKEN"],
            )
        )
        stream = response.body_iterator
        first = await anext(stream)
        assert json.loads(first[6:])["choices"][0]["delta"]["content"] == "Partial"
        await stream.aclose()

    assert store.get_messages(session.id) == []
    assert store.get_session(session.id).backend_uuid is None


def test_bound_account_failure_does_not_claim_another_account(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    session = store.create_session()
    store.bind_client_once(session.id, "account-a")
    pool = make_pool("account-b")

    with (
        patch("perplexity.server.webui.get_pool", return_value=pool),
        patch(
            "perplexity.server.webui.run_query",
            return_value={
                "status": "error",
                "error_type": "RuntimeError",
                "message": "Bound account 'account-a' is unavailable for this session.",
            },
        ) as run,
    ):
        with pytest.raises(webui.WebUIChatError, match="Bound account"):
            webui._run_session_non_stream(
                store,
                session.id,
                user_message={"role": "user", "content": "question"},
                query="question",
                files={},
                mode="auto",
                model=None,
                model_id="perplexity-search",
            )

    assert run.call_args.args[8] == "account-a"
    pool.get_client.assert_not_called()
    assert store.get_session(session.id).client_id == "account-a"
