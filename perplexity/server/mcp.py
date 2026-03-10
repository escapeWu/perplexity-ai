"""
MCP tools for Perplexity search.
Provides list_models, search, research, and toggle_builtin_tools tools.
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

    ⚡ 特点: 速度快，适合需要实时信息的简单查询

    Args:
        query: 搜索问题 (清晰、具体的问题效果更好)
        mode: 搜索模式
            - 'auto': 快速模式，使用 turbo 模型，不消耗额度
            - 'pro': 专业模式，更准确的结果 (默认)
        model: 指定模型 (仅 pro 模式生效)
            - None: 使用默认模型 (推荐)
            - 'sonar': Perplexity 自研模型
            - 'gpt-5.4': OpenAI 最新模型
            - 'claude-4.6-sonnet': Anthropic Claude
            - 'gemini-3.1-pro': Google Gemini Pro
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
    # 使用 asyncio.to_thread 避免阻塞事件循环
    return await asyncio.to_thread(
        run_query, query, mode, model, sources, language, incognito, files, fallback_to_auto
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

    🧠 特点: 使用推理模型，会进行多步思考，结果更全面准确，但耗时较长

    Args:
        query: 研究问题 (问题越具体，研究结果越有针对性)
        mode: 研究模式
            - 'reasoning': 推理模式，多步思考分析 (默认)
            - 'deep research': 深度研究，最全面但最耗时
        model: 指定推理模型 (仅 reasoning 模式生效)
            - 'gemini-3.1-pro': Google Gemini Pro (默认，推荐)
            - 'gpt-5.4-thinking': OpenAI 思考模型
            - 'claude-4.6-sonnet-thinking': Claude 推理模型
            - 'kimi-k2-thinking': Moonshot Kimi
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
    # 使用 asyncio.to_thread 避免阻塞事件循环
    return await asyncio.to_thread(
        run_query, query, mode, model, sources, language, incognito, files, fallback_to_auto
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
        return json.dumps({
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
        }, ensure_ascii=False)

    elif action in ("off", "disable"):
        return json.dumps({
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
        }, ensure_ascii=False)

    else:
        return json.dumps({
            "action": "check_status",
            "instruction": (
                f"请在本地执行以下操作：\n"
                f"1. 读取 {SETTINGS_FILE} 文件\n"
                f"2. 检查 permissions.deny 数组中是否包含 {DENY_TOOLS}\n"
                f"3. 告知用户当前内置搜索工具的启用/禁用状态。"
            ),
            "target_file": SETTINGS_FILE,
            "tools_to_check": DENY_TOOLS,
        }, ensure_ascii=False)
