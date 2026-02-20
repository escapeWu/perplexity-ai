# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Perplexity MCP Server - An unofficial Python API for Perplexity.ai that exposes search capabilities via MCP (Model Context Protocol) and OpenAI-compatible endpoints. Supports multi-token pools for load balancing, health monitoring, and various search modes.

## Commands

```bash
# Install dependencies
uv sync

# Run the server (default: HTTP on port 8000)
uv run perplexity

# Run with specific transport
uv run perplexity --transport http --host 0.0.0.0 --port 8000

# Run tests
uv run pytest

# Run a single test file
uv run pytest tests/test_client_pool.py

# Run with coverage
uv run pytest --cov=perplexity

# Format code
uv run black perplexity tests
uv run isort perplexity tests

# Docker deployment
docker compose up -d
```

## Architecture

**Core Flow**: `main.py` → `app.py` (FastMCP instance + middleware) → route modules (`mcp.py`, `oai.py`, `admin.py`)

**Key Components**:
- `perplexity/server/app.py` - FastMCP app, auth middleware, `run_query()` core logic, ClientPool singleton
- `perplexity/server/mcp.py` - MCP tool definitions: `list_models`, `search`, `research`
- `perplexity/server/oai.py` - OpenAI-compatible API: `/v1/models`, `/v1/chat/completions`
- `perplexity/server/admin.py` - Health check, token pool management, heartbeat control
- `perplexity/server/client_pool.py` - Multi-account connection pool with load balancing and exponential backoff
- `perplexity/client.py` - Low-level Perplexity API client using WebSocket

**Configuration**:
- `token_pool_config.json` - Token pool and heartbeat settings
- Environment variables: `MCP_TOKEN`, `PPLX_ADMIN_TOKEN`, `SOCKS_PROXY`

## Code Style

- Line length: 100 characters (black/isort configured in pyproject.toml)
- Python 3.10+
- Use type hints where appropriate

## Web Search

Use `perplexity-mcp` tools instead of `webSearch` for web search functionality.
