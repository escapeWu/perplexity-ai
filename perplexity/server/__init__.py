"""
Perplexity MCP Server package.
Provides both MCP tools and OpenAI-compatible API endpoints.
"""

from .app import get_pool, mcp
from .main import main, run_server

# Import tools to ensure they're registered
from .mcp import (  # noqa: F401
    list_models,
    perplexity_ask,
    perplexity_ask_v2,
    perplexity_reason,
    perplexity_research,
    perplexity_research_v2,
    perplexity_search,
    research,
    search,
)

__all__ = [
    "mcp",
    "get_pool",
    "run_server",
    "main",
    "list_models",
    "search",
    "research",
    "perplexity_ask",
    "perplexity_ask_v2",
    "perplexity_search",
    "perplexity_reason",
    "perplexity_research",
    "perplexity_research_v2",
]
