"""
MCP tools for Perplexity search.
Provides model discovery, parameterized search/research tools, and simple agent-friendly aliases.
"""

import asyncio
import json
from typing import Any, Dict, Iterable, List, Optional, Union

try:
    from ..config import LABS_MODELS, MODEL_MAPPINGS, SEARCH_MODES
except ImportError:
    from perplexity.config import LABS_MODELS, MODEL_MAPPINGS, SEARCH_MODES

try:
    from .app import mcp, run_query
except ImportError:
    from perplexity.server.app import mcp, run_query

# If mcp is None (e.g. testing env), create a dummy decorator
if mcp is None:

    class DummyMCP:
        def tool(self, func):
            return func

    mcp = DummyMCP()


def list_models_tool() -> Dict[str, Any]:
    """Return supported modes, model mappings, and Labs models."""
    return {
        "modes": SEARCH_MODES,
        "model_mappings": MODEL_MAPPINGS,
        "labs_models": LABS_MODELS,
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


@mcp.tool
def list_models() -> Dict[str, Any]:
    """
    获取 Perplexity 支持的所有搜索模式和模型列表

    当你需要了解可用的模型选项时调用此工具。

    Returns:
        包含 modes (搜索模式)、model_mappings (模型映射) 和 labs_models (实验模型) 的字典
    """
    return list_models_tool()


@mcp.tool
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
            - 'gemini-3.1-pro': Google Gemini Pro
            - 'grok-4.5': xAI Grok 4.5
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


@mcp.tool
async def research(
    query: str,
    mode: str = "reasoning",
    model: Optional[str] = "gemini-3.1-pro",
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
            - 'gemini-3.1-pro': Google Gemini Pro (默认，推荐)
            - 'gpt-5.6-terra-thinking': OpenAI GPT-5.6 Terra Thinking
            - 'claude-sonnet-5-thinking': Claude Sonnet 5 Thinking
            - 'kimi-k3-thinking': Moonshot Kimi K3
            - 'glm-5.2': Z.ai GLM 5.2
            - 'grok-4.5-thinking': xAI Grok 4.5 Thinking
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


@mcp.tool
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


@mcp.tool
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


@mcp.tool
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


@mcp.tool
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


@mcp.tool
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
