"""Tests for session-aware v2 MCP tools and legacy deprecation metadata."""

import importlib
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from perplexity.server.app import mcp as fastmcp_app
from perplexity.server.webui_sessions import WebUISessionStore

mcp_tools = importlib.import_module("perplexity.server.mcp")


def make_pool(client_id="account-a"):
    pool = MagicMock()
    pool.clients = {client_id: object()}
    pool.get_client.return_value = (client_id, object())
    pool.get_client_state.return_value = "normal"
    pool.get_model_subscription_tiers.return_value = {"pro"}
    return pool


@pytest.mark.asyncio
async def test_ask_v2_defaults_model_returns_session_and_continues(api_runtime):
    source = api_runtime.test_upstream
    source.release["First question"].set()
    source.release["Second question"].set()
    first = await mcp_tools.perplexity_ask_v2.fn(" First question ")
    second = await mcp_tools.perplexity_ask_v2.fn("Second question", session_id=first["session_id"])
    assert first["status"] == "ok"
    assert first["model"] == "perplexity-search"
    assert "_follow_up" not in first["data"]
    assert second["session_id"] == first["session_id"]
    assert second["data"]["answer"] == "Second question partial complete"
    session = api_runtime.sessions.get_session(first["session_id"])
    assert session.origin == "mcp"
    assert session.client_id == "one-account"
    assert session.backend_uuid == "backend-Second question"
    assert source.calls[1]["follow_up"] == {"backend_uuid": "backend-First question", "attachments": []}


@pytest.mark.asyncio
async def test_ask_v2_uses_oai_model_and_thinking_resolution(monkeypatch):
    pool = make_pool()
    captured = {}

    def fake_parse(model_id, thinking, tiers):
        captured.update(model_id=model_id, thinking=thinking, tiers=tiers)
        return "reasoning", "gpt-5.6-terra-thinking", "gpt-5-6-terra-thinking"

    run = AsyncMock(
        return_value={
            "status": "ok",
            "session_id": "sess_00000000000000000000000000000000",
            "model": "gpt-5-6-terra-thinking",
            "data": {"answer": "ok", "sources": []},
        }
    )
    monkeypatch.setattr(mcp_tools, "get_pool", lambda: pool)
    monkeypatch.setattr(mcp_tools, "parse_oai_model_with_thinking", fake_parse)
    monkeypatch.setattr(mcp_tools, "_run_v2_session_query", run)

    result = await mcp_tools.perplexity_ask_v2.fn("analyze", model="gpt-5-6-terra", thinking=True)

    assert result["model"] == "gpt-5-6-terra-thinking"
    assert captured == {
        "model_id": "gpt-5-6-terra",
        "thinking": True,
        "tiers": {"pro"},
    }
    assert run.await_args.kwargs["mode"] == "reasoning"
    assert run.await_args.kwargs["model"] == "gpt-5.6-terra-thinking"


@pytest.mark.asyncio
async def test_research_v2_uses_deep_research_model(monkeypatch):
    pool = make_pool()
    run = AsyncMock(return_value={"status": "ok", "session_id": "sess_test"})
    monkeypatch.setattr(mcp_tools, "get_pool", lambda: pool)
    monkeypatch.setattr(
        mcp_tools,
        "parse_oai_model",
        lambda model_id, tiers: ("deep research", None),
    )
    monkeypatch.setattr(mcp_tools, "_run_v2_session_query", run)

    await mcp_tools.perplexity_research_v2.fn("research this")

    assert run.await_args.kwargs["mode"] == "deep research"
    assert run.await_args.kwargs["model"] is None
    assert run.await_args.kwargs["model_id"] == "perplexity-deepsearch"


@pytest.mark.asyncio
async def test_ask_v2_unknown_session_returns_structured_error(api_runtime):
    session_id = "sess_00000000000000000000000000000000"
    result = await mcp_tools.perplexity_ask_v2.fn("hello", session_id=session_id)

    assert result == {
        "status": "error",
        "error_type": "SessionNotFound",
        "message": "Session not found",
        "session_id": session_id,
    }


@pytest.mark.asyncio
async def test_all_legacy_tools_are_marked_pending_removal():
    tools = await fastmcp_app.get_tools()
    legacy_names = {
        "list_models",
        "search",
        "research",
        "perplexity_ask",
        "perplexity_search",
        "perplexity_reason",
        "perplexity_research",
        "toggle_builtin_tools",
    }

    for name in legacy_names:
        tool = tools[name]
        assert tool.meta["deprecated"] is True
        assert tool.meta["deprecation_status"] == "pending_removal"
        assert "deprecated" in tool.tags
        assert tool.description.startswith("DEPRECATED:")

    for name in {"perplexity_ask_v2", "perplexity_research_v2"}:
        assert tools[name].meta == {"version": "v2"}
        assert "deprecated" not in tools[name].tags
