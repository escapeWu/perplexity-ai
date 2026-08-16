"""
MCP tools for Perplexity search.
Provides model discovery, parameterized search/research tools, and simple agent-friendly aliases.
"""

import asyncio
import json
from typing import Any, Callable, Dict, Iterable, List, Optional, Union

try:
    from ..config import SEARCH_MODES
    from ..model_registry import get_model_registry
except ImportError:
    from perplexity.config import SEARCH_MODES
    from perplexity.model_registry import get_model_registry

try:
    from .app import get_pool, mcp, run_query
except ImportError:
    from perplexity.server.app import get_pool, mcp, run_query

try:
    from .session_runtime import SessionChatError, get_or_create_session, run_session_non_stream
    from .utils import parse_oai_model, parse_oai_model_with_thinking
    from .webui_sessions import (
        InvalidWebUISession,
        WebUISessionNotFound,
        get_webui_session_store,
    )
except ImportError:
    from perplexity.server.session_runtime import (
        SessionChatError,
        get_or_create_session,
        run_session_non_stream,
    )
    from perplexity.server.utils import parse_oai_model, parse_oai_model_with_thinking
    from perplexity.server.webui_sessions import (
        InvalidWebUISession,
        WebUISessionNotFound,
        get_webui_session_store,
    )

# If mcp is None (e.g. testing env), create a dummy decorator
if mcp is None:

    class DummyMCP:
        def tool(self, func=None, **kwargs):
            del kwargs
            if func is None:
                return lambda decorated: decorated
            return func

    mcp = DummyMCP()


def _deprecated_tool(replacement: Optional[str] = None) -> Callable:
    """Register an old tool with human- and machine-readable deprecation markers."""

    def decorator(func: Callable) -> Any:
        replacement_text = f" Use `{replacement}` instead." if replacement else ""
        notice = (
            "DEPRECATED: This tool is retained for compatibility and will be removed in "
            f"a future release.{replacement_text}"
        )
        func.__doc__ = f"{notice}\n\n{(func.__doc__ or '').strip()}"
        metadata: Dict[str, Any] = {
            "deprecated": True,
            "deprecation_status": "pending_removal",
        }
        if replacement:
            metadata["replacement"] = replacement
        return mcp.tool(tags={"deprecated"}, meta=metadata)(func)

    return decorator


def list_models_tool(
    subscription_tiers: Optional[Iterable[str]] = None,
) -> Dict[str, Any]:
    """Return supported modes and model mappings."""
    return {
        "modes": SEARCH_MODES,
        "model_mappings": get_model_registry().get_model_mappings(subscription_tiers),
    }


async def _run_query_async(
    query: str,
    mode: str,
    model: Optional[str] = None,
    sources: Optional[List[str]] = None,
    language: str = "en-US",
    incognito: bool = False,
    files: Optional[Union[Dict[str, Any], Iterable[str]]] = None,
    fallback_to_auto: bool = True,
) -> Dict[str, Any]:
    """Run the shared query pipeline without blocking the MCP event loop."""
    return await asyncio.to_thread(
        run_query, query, mode, model, sources, language, incognito, files, fallback_to_auto
    )


def _mcp_session_error(exc: Exception, session_id: Optional[str] = None) -> Dict[str, Any]:
    if isinstance(exc, WebUISessionNotFound):
        error_type = "SessionNotFound"
    elif isinstance(exc, (InvalidWebUISession, ValueError)):
        error_type = "ValidationError"
    elif isinstance(exc, SessionChatError):
        error_type = exc.error_type
    else:
        error_type = type(exc).__name__
    result: Dict[str, Any] = {
        "status": "error",
        "error_type": error_type,
        "message": str(exc),
    }
    if session_id is not None:
        result["session_id"] = session_id
    return result


async def _run_v2_session_query(
    query: str,
    *,
    mode: str,
    model: Optional[str],
    model_id: str,
    session_id: Optional[str],
    files: Optional[Union[Dict[str, Any], Iterable[str]]],
) -> Dict[str, Any]:
    """Execute a v2 MCP turn through the same native session runtime as OAI/WebUI."""
    resolved_session_id = session_id
    try:
        store = get_webui_session_store()
        session = get_or_create_session(store, session_id, origin="mcp")
        resolved_session_id = session.id
        data, _ = await asyncio.to_thread(
            run_session_non_stream,
            store,
            session.id,
            user_content=query,
            query=query,
            files=files or {},
            mode=mode,
            model=model,
            model_id=model_id,
        )
    except Exception as exc:
        return _mcp_session_error(exc, resolved_session_id)

    public_data = dict(data)
    public_data.pop("_follow_up", None)
    return {
        "status": "ok",
        "session_id": session.id,
        "model": model_id,
        "data": public_data,
    }


@mcp.tool(tags={"v2", "session"}, meta={"version": "v2"})
async def perplexity_ask_v2(
    query: str,
    model: Optional[str] = None,
    thinking: bool = False,
    session_id: Optional[str] = None,
    files: Optional[Union[Dict[str, Any], Iterable[str]]] = None,
) -> Dict[str, Any]:
    """Ask Perplexity with an OAI model ID and an optional native conversation session.

    Omit ``model`` to use ``perplexity-search``. Set ``thinking=true`` to resolve
    the selected model's paired thinking variant. Omit ``session_id`` to start a
    new conversation; the returned ID can be supplied on the next call.
    """
    if not isinstance(query, str) or not query.strip():
        return _mcp_session_error(ValueError("query must be a non-empty string"), session_id)
    if not isinstance(thinking, bool):
        return _mcp_session_error(ValueError("thinking must be a boolean"), session_id)
    if model is not None and (not isinstance(model, str) or not model.strip()):
        return _mcp_session_error(
            ValueError("model must be a non-empty OAI model ID when provided"), session_id
        )

    requested_model_id = model if model is not None else "perplexity-search"
    try:
        mode, internal_model, effective_model_id = parse_oai_model_with_thinking(
            requested_model_id,
            thinking,
            get_pool().get_model_subscription_tiers(),
        )
        if mode == "deep research":
            raise ValueError(
                "perplexity_ask_v2 does not accept the Deep Research model; "
                "use perplexity_research_v2"
            )
    except ValueError as exc:
        return _mcp_session_error(exc, session_id)

    return await _run_v2_session_query(
        query.strip(),
        mode=mode,
        model=internal_model,
        model_id=effective_model_id,
        session_id=session_id,
        files=files,
    )


@mcp.tool(tags={"v2", "session"}, meta={"version": "v2"})
async def perplexity_research_v2(
    query: str,
    session_id: Optional[str] = None,
    files: Optional[Union[Dict[str, Any], Iterable[str]]] = None,
) -> Dict[str, Any]:
    """Run Deep Research with an optional native conversation session.

    Omit ``session_id`` to start a new conversation; pass the returned ID to
    continue the same upstream thread on its permanently bound account.
    """
    if not isinstance(query, str) or not query.strip():
        return _mcp_session_error(ValueError("query must be a non-empty string"), session_id)

    try:
        mode, internal_model = parse_oai_model(
            "perplexity-deepsearch",
            get_pool().get_model_subscription_tiers(),
        )
    except ValueError as exc:
        return _mcp_session_error(exc, session_id)

    return await _run_v2_session_query(
        query.strip(),
        mode=mode,
        model=internal_model,
        model_id="perplexity-deepsearch",
        session_id=session_id,
        files=files,
    )


@_deprecated_tool("GET /v1/models")
def list_models() -> Dict[str, Any]:
    """
    获取 Perplexity 支持的所有搜索模式和模型列表

    当你需要了解可用的模型选项时调用此工具。

    Returns:
        包含 modes (搜索模式) 和 model_mappings (模型映射) 的字典
    """
    return list_models_tool(get_pool().get_model_subscription_tiers())


@_deprecated_tool("perplexity_ask_v2")
async def search(
    query: str,
    mode: str = "pro",
    model: Optional[str] = None,
    sources: Optional[List[str]] = None,
    language: str = "en-US",
    incognito: bool = False,
    files: Optional[Union[Dict[str, Any], Iterable[str]]] = None,
    fallback_to_auto: bool = True,
) -> Dict[str, Any]:
    """
    Perplexity 快速搜索 - 用于获取实时网络信息和简单问题解答

    适合需要最新网页信息、事实核查、新闻动态、资料检索和简短综合回答的场景。
    如果只是普通问答且不需要 Pro 搜索，优先使用 perplexity_ask。
    如果需要多步推理或深度调研，使用 research / perplexity_reason / perplexity_research。

    Args:
        query: 搜索问题 (清晰、具体的问题效果更好)
        mode: 搜索模式
            - 'auto': 快速模式，使用 turbo 模型，不消耗额度
            - 'pro': 专业模式，更准确的结果 (默认)
        model: 指定模型 (仅 pro 模式生效)
            - None: 使用默认模型 (推荐)
            - 'sonar-2': Perplexity Sonar 2 ('sonar' 为兼容别名)
            - 'gpt-5.6-terra': OpenAI GPT-5.6 Terra
            - 'claude-sonnet-5': Anthropic Claude Sonnet 5
            - 'gemini-3.7-flash': Google Gemini 3.7 Flash
            - 'grok-4.6': xAI Grok 4.6
        sources: 搜索来源列表
            - 'web': 网页搜索 (默认)
            - 'scholar': 学术论文
            - 'social': 社交媒体
        language: 响应语言代码 (默认 'en-US'，中文用 'zh-CN')
        incognito: 隐身模式，不保存搜索历史
        files: 上传文件 (用于分析文档内容)
        fallback_to_auto: 当所有客户端失败时，是否降级到匿名 auto 模式 (默认 True)

    Returns:
        {"status": "ok", "data": {"answer": "搜索结果...", "sources": [{"title": "...", "url": "..."}]}}
        或 {"status": "error", "error_type": "...", "message": "..."}
    """
    # 限制 search 只能使用 auto 或 pro 模式
    if mode not in ["auto", "pro"]:
        mode = "pro"
    return await _run_query_async(
        query, mode, model, sources, language, incognito, files, fallback_to_auto
    )


@_deprecated_tool("perplexity_research_v2")
async def research(
    query: str,
    mode: str = "reasoning",
    model: Optional[str] = "gemini-3.7-flash-thinking",
    sources: Optional[List[str]] = None,
    language: str = "en-US",
    incognito: bool = False,
    files: Optional[Union[Dict[str, Any], Iterable[str]]] = None,
    fallback_to_auto: bool = True,
) -> Dict[str, Any]:
    """
    Perplexity 深度研究 - 用于复杂问题分析和深度调研

    适合复杂分析、方案比较、技术调研、学术资料整理和需要明确推理路径的问题。
    普通实时搜索请使用 search / perplexity_search；日常简短问答请使用 perplexity_ask。
    deep research 通常更慢，适合值得等待的综合研究任务。

    Args:
        query: 研究问题 (问题越具体，研究结果越有针对性)
        mode: 研究模式
            - 'reasoning': 推理模式，多步思考分析 (默认)
            - 'deep research': 深度研究，最全面但最耗时
        model: 指定推理模型 (仅 reasoning 模式生效)
            - 'gemini-3.7-flash-thinking': Google Gemini 3.7 Flash Thinking (默认，推荐)
            - 'gpt-5.6-terra-thinking': OpenAI GPT-5.6 Terra Thinking
            - 'claude-sonnet-5-thinking': Claude Sonnet 5 Thinking
            - 'kimi-k3-thinking': Moonshot Kimi K3
            - 'glm-5.2': Z.ai GLM 5.2
            - 'grok-4.6-thinking': xAI Grok 4.6 Thinking
            - 'nemotron-3-ultra': NVIDIA Nemotron 3 Ultra
        sources: 搜索来源列表
            - 'web': 网页搜索 (默认)
            - 'scholar': 学术论文 (学术研究推荐)
            - 'social': 社交媒体
        language: 响应语言代码 (默认 'en-US'，中文用 'zh-CN')
        incognito: 隐身模式，不保存搜索历史
        files: 上传文件 (用于分析文档内容)
        fallback_to_auto: 当所有客户端失败时，是否降级到匿名 auto 模式 (默认 True)

    Returns:
        {"status": "ok", "data": {"answer": "研究结果...", "sources": [{"title": "...", "url": "..."}]}}
        或 {"status": "error", "error_type": "...", "message": "..."}
    """
    # 限制 research 只能使用 reasoning 或 deep research 模式
    if mode not in ["reasoning", "deep research"]:
        mode = "reasoning"
    # deep research 模式不支持指定 model
    if mode == "deep research":
        model = None
    return await _run_query_async(
        query, mode, model, sources, language, incognito, files, fallback_to_auto
    )


@_deprecated_tool("perplexity_ask_v2")
async def perplexity_ask(
    query: str,
    language: str = "en-US",
    incognito: bool = False,
    fallback_to_auto: bool = True,
) -> Dict[str, Any]:
    """
    Ask Perplexity a concise general-purpose question using auto mode.

    Use this as the default low-cost entry point for factual questions, quick explanations,
    summaries, definitions, and everyday lookups where a full Pro search is unnecessary.
    It does not accept model selection, source filtering, or file uploads; use search/research
    when those controls matter.
    """
    return await _run_query_async(
        query,
        "auto",
        None,
        None,
        language,
        incognito,
        None,
        fallback_to_auto,
    )


@_deprecated_tool("perplexity_ask_v2")
async def perplexity_search(
    query: str,
    language: str = "en-US",
    incognito: bool = False,
    fallback_to_auto: bool = True,
) -> Dict[str, Any]:
    """
    Search the web with Perplexity Pro and return a synthesized answer with sources.

    Use this for current events, recent developments, web-backed fact checking, and queries
    where citations or source links are important. It searches web sources with the default
    Pro model; use search when you need another model, scholar/social sources, or file input.
    """
    return await _run_query_async(
        query,
        "pro",
        None,
        ["web"],
        language,
        incognito,
        None,
        fallback_to_auto,
    )


@_deprecated_tool("perplexity_ask_v2")
async def perplexity_reason(
    query: str,
    language: str = "en-US",
    incognito: bool = False,
    fallback_to_auto: bool = True,
) -> Dict[str, Any]:
    """
    Ask Perplexity to reason through a complex problem using the default reasoning model.

    Use this for multi-step analysis, debugging hypotheses, tradeoff decisions, math or logic
    problems, and questions where reasoning quality matters more than speed. Use research when
    you need to choose a specific reasoning model or include files/sources.
    """
    return await _run_query_async(
        query,
        "reasoning",
        None,
        None,
        language,
        incognito,
        None,
        fallback_to_auto,
    )


@_deprecated_tool("perplexity_research_v2")
async def perplexity_research(
    query: str,
    language: str = "en-US",
    incognito: bool = False,
    fallback_to_auto: bool = True,
) -> Dict[str, Any]:
    """
    Conduct deeper Perplexity research for broad or high-effort investigation tasks.

    Use this when the user asks for a comprehensive report, topic survey, market or technical
    research, or a synthesis that benefits from multi-step exploration. It can be slow; use
    perplexity_ask or perplexity_search for quick answers.
    """
    return await _run_query_async(
        query,
        "deep research",
        None,
        None,
        language,
        incognito,
        None,
        fallback_to_auto,
    )


@_deprecated_tool()
def toggle_builtin_tools(action: str = "status") -> str:
    """
    开关 Claude Code 内置的 WebSearch 和 WebFetch 工具。

    禁用内置工具后，Claude Code 将只能使用 perplexity-mcp 提供的 search/research 进行网络搜索。

    Parameters:
        action: 操作类型
            - "on" 或 "enable": 禁用内置 WebSearch/WebFetch（使用 perplexity-mcp 替代）
            - "off" 或 "disable": 恢复内置 WebSearch/WebFetch
            - "status": 查看当前状态（默认）

    Returns:
        JSON with instructions for the Claude Code client to execute locally
    """
    SETTINGS_FILE = "~/.claude/settings.json"
    DENY_TOOLS = ["WebFetch", "WebSearch"]

    if action in ("on", "enable"):
        return json.dumps(
            {
                "action": "block_builtin_tools",
                "instruction": (
                    f"请在本地执行以下操作：\n"
                    f"1. 读取 {SETTINGS_FILE} 文件\n"
                    f"2. 在 JSON 中找到或创建 permissions.deny 数组\n"
                    f"3. 将 {DENY_TOOLS} 添加到 deny 数组中（如果不存在）\n"
                    f"4. 写回文件\n"
                    f"这将禁用 Claude Code 内置的 WebSearch/WebFetch，"
                    f"后续搜索将使用 perplexity-mcp 的 search/research 工具。"
                ),
                "target_file": SETTINGS_FILE,
                "tools_to_deny": DENY_TOOLS,
            },
            ensure_ascii=False,
        )

    elif action in ("off", "disable"):
        return json.dumps(
            {
                "action": "unblock_builtin_tools",
                "instruction": (
                    f"请在本地执行以下操作：\n"
                    f"1. 读取 {SETTINGS_FILE} 文件\n"
                    f"2. 从 permissions.deny 数组中移除 {DENY_TOOLS}\n"
                    f"3. 写回文件\n"
                    f"这将恢复 Claude Code 内置的 WebSearch/WebFetch 工具。"
                ),
                "target_file": SETTINGS_FILE,
                "tools_to_deny": DENY_TOOLS,
            },
            ensure_ascii=False,
        )

    else:
        return json.dumps(
            {
                "action": "check_status",
                "instruction": (
                    f"请在本地执行以下操作：\n"
                    f"1. 读取 {SETTINGS_FILE} 文件\n"
                    f"2. 检查 permissions.deny 数组中是否包含 {DENY_TOOLS}\n"
                    f"3. 告知用户当前内置搜索工具的启用/禁用状态。"
                ),
                "target_file": SETTINGS_FILE,
                "tools_to_check": DENY_TOOLS,
            },
            ensure_ascii=False,
        )
