"""
Main entry point for Perplexity MCP server.
Imports all route modules to register them with the FastMCP app.
"""

import argparse

# Initialize logging before importing other modules
from ..logger import setup_logger

setup_logger()

from . import admin  # noqa: F401
from . import oai  # noqa: F401
from . import webui  # noqa: F401
from .app import get_pool, mcp

# Import route modules to register tools and endpoints with the mcp instance
# Must import the actual decorated functions to trigger registration
from .mcp import (  # noqa: F401
    list_models,
    perplexity_ask,
    perplexity_reason,
    perplexity_research,
    perplexity_search,
    research,
    search,
)


def run_server(
    transport: str = "http",
    host: str = "0.0.0.0",
    port: int = 8000,
) -> None:
    """Start the MCP server with the requested transport."""
    # Initialize the pool on startup
    get_pool()

    if transport == "http":
        mcp.run(transport="http", host=host, port=port)
    else:
        mcp.run()


def main() -> None:
    parser = argparse.ArgumentParser(description="Run Perplexity MCP server (fastmcp).")
    parser.add_argument(
        "--transport",
        choices=["stdio", "http"],
        default="http",
        help="Transport to use for MCP server.",
    )
    parser.add_argument("--host", default="0.0.0.0", help="HTTP host (when transport=http).")
    parser.add_argument("--port", type=int, default=8000, help="HTTP port (when transport=http).")
    args = parser.parse_args()
    run_server(transport=args.transport, host=args.host, port=args.port)


if __name__ == "__main__":
    main()
