"""Unit tests for agent-friendly MCP alias tools."""

from typing import Any, Dict, List

import pytest

from perplexity.config import LABS_MODELS, MODEL_MAPPINGS, SEARCH_MODES
from perplexity.server import mcp as mcp_module


def test_list_models_tool_uses_canonical_config() -> None:
    assert mcp_module.list_models_tool() == {
        "modes": SEARCH_MODES,
        "model_mappings": MODEL_MAPPINGS,
        "labs_models": LABS_MODELS,
    }


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("tool_name", "expected_mode", "expected_sources"),
    [
        ("perplexity_ask", "auto", None),
        ("perplexity_search", "pro", ["web"]),
        ("perplexity_reason", "reasoning", None),
        ("perplexity_research", "deep research", None),
    ],
)
async def test_alias_tools_delegate_to_expected_query_mode(
    monkeypatch: pytest.MonkeyPatch,
    tool_name: str,
    expected_mode: str,
    expected_sources: List[str] | None,
) -> None:
    calls: List[Dict[str, Any]] = []

    async def fake_run_query_async(
        query: str,
        mode: str,
        model: str | None = None,
        sources: List[str] | None = None,
        language: str = "en-US",
        incognito: bool = False,
        files: Any = None,
        fallback_to_auto: bool = True,
    ) -> Dict[str, Any]:
        calls.append(
            {
                "query": query,
                "mode": mode,
                "model": model,
                "sources": sources,
                "language": language,
                "incognito": incognito,
                "files": files,
                "fallback_to_auto": fallback_to_auto,
            }
        )
        return {"status": "ok", "data": {"answer": "stub", "sources": []}}

    monkeypatch.setattr(mcp_module, "_run_query_async", fake_run_query_async)

    tool = getattr(mcp_module, tool_name).fn
    result = await tool(
        "hello",
        language="zh-CN",
        incognito=True,
        fallback_to_auto=False,
    )

    assert result["status"] == "ok"
    assert calls == [
        {
            "query": "hello",
            "mode": expected_mode,
            "model": None,
            "sources": expected_sources,
            "language": "zh-CN",
            "incognito": True,
            "files": None,
            "fallback_to_auto": False,
        }
    ]
