"""
FastMCP application instance and shared utilities.
"""

import os
from contextlib import asynccontextmanager
from typing import Any, Dict, Iterable, List, Optional, Union

from fastmcp import FastMCP
from fastmcp.server.middleware import Middleware, MiddlewareContext
from fastmcp.server.dependencies import get_http_headers
from starlette.applications import Starlette

from .client_pool import ClientPool
from ..client import Client
from ..config import SEARCH_LANGUAGES
from ..exceptions import ValidationError
from ..logger import get_logger

from .utils import (
    sanitize_query, validate_file_data, validate_query_limits, validate_search_params,
)

logger = get_logger("server.app")

# API 密钥配置（从环境变量读取，默认为 sk-123456）
MCP_TOKEN = os.getenv("MCP_TOKEN", "sk-123456")

# 全局 ClientPool 实例
_pool: Optional[ClientPool] = None


def get_pool() -> ClientPool:
    """Get or create the singleton ClientPool instance."""
    global _pool
    if _pool is None:
        _pool = ClientPool()
    return _pool


@asynccontextmanager
async def app_lifespan(server: FastMCP):
    """Application lifespan handler for startup/shutdown events."""
    # Startup: Initialize pool and start heartbeat
    pool = get_pool()
    if pool.is_heartbeat_enabled():
        pool.start_heartbeat()
        logger.info("Heartbeat started via lifespan")
    yield
    # Shutdown: Stop heartbeat gracefully
    pool.stop_heartbeat()
    logger.info("Heartbeat stopped via lifespan")


class AuthMiddleware(Middleware):
    """Bearer Token 认证中间件"""

    def __init__(self, token: str):
        self.token = token

    async def on_request(self, context: MiddlewareContext, call_next):
        """验证请求的 Authorization header"""
        headers = get_http_headers()
        if headers:  # HTTP 模式下才有 headers
            auth = headers.get("authorization") or headers.get("Authorization")
            if auth != f"Bearer {self.token}":
                raise PermissionError("Unauthorized: Invalid or missing Bearer token")
        return await call_next(context)


# Create FastMCP instance with lifespan
mcp = FastMCP("perplexity-mcp", lifespan=app_lifespan)

# 添加认证中间件
mcp.add_middleware(AuthMiddleware(MCP_TOKEN))


def get_pool() -> ClientPool:
    """Get or create the singleton ClientPool instance."""
    global _pool
    if _pool is None:
        _pool = ClientPool()
    return _pool


def normalize_files(files: Optional[Union[Dict[str, Any], Iterable[str]]]) -> Dict[str, Any]:
    """
    Accept either a dict of filename->data or an iterable of file paths,
    and normalize to the dict format expected by Client.search.
    """
    if not files:
        return {}

    if isinstance(files, dict):
        normalized = files
    else:
        normalized = {}
        for path in files:
            filename = os.path.basename(path)
            with open(path, "rb") as fh:
                normalized[filename] = fh.read()

    validate_file_data(normalized)
    return normalized


def extract_clean_result(response: Dict[str, Any]) -> Dict[str, Any]:
    """Extract the final answer and source links from the search response."""
    result = {}

    # 提取最终答案
    if "answer" in response:
        result["answer"] = response["answer"]

    # 提取来源链接
    sources = []

    # 方法1: 从 text 字段的 SEARCH_RESULTS 步骤中提取 web_results
    if "text" in response and isinstance(response["text"], list):
        for step in response["text"]:
            if isinstance(step, dict) and step.get("step_type") == "SEARCH_RESULTS":
                content = step.get("content", {})
                web_results = content.get("web_results", [])
                for web_result in web_results:
                    if isinstance(web_result, dict) and "url" in web_result:
                        source = {"url": web_result["url"]}
                        if "name" in web_result:
                            source["title"] = web_result["name"]
                        sources.append(source)

    # 方法2: 备用 - 从 chunks 字段提取（如果 chunks 包含 URL）
    if not sources and "chunks" in response and isinstance(response["chunks"], list):
        for chunk in response["chunks"]:
            if isinstance(chunk, dict):
                source = {}
                if "url" in chunk:
                    source["url"] = chunk["url"]
                if "title" in chunk:
                    source["title"] = chunk["title"]
                if "name" in chunk and "title" not in source:
                    source["title"] = chunk["name"]
                if "url" in source:
                    sources.append(source)

    result["sources"] = sources

    return result


def run_query(
    query: str,
    mode: str,
    model: Optional[str] = None,
    sources: Optional[List[str]] = None,
    language: str = "en-US",
    incognito: bool = False,
    files: Optional[Union[Dict[str, Any], Iterable[str]]] = None,
    fallback_to_auto: bool = True,
) -> Dict[str, Any]:
    """
    Execute a Perplexity query with client pool rotation and optional fallback.

    Features:
    - Rotates through all available clients in the pool on failure
    - No per-client retry - fails fast and moves to next client
    - Falls back to anonymous auto mode if all clients fail (when enabled)
    - Validates query and files once before execution

    Args:
        fallback_to_auto: If True, attempt anonymous auto mode search when all clients fail
    """
    pool = get_pool()

    # --- 1. Stateless Validation ---
    try:
        clean_query = sanitize_query(query)
        chosen_sources = sources or ["web"]

        # Ensure SEARCH_LANGUAGES is not None before using 'in'
        if SEARCH_LANGUAGES is None or language not in SEARCH_LANGUAGES:
            valid_langs = ', '.join(SEARCH_LANGUAGES) if SEARCH_LANGUAGES else "en-US"
            raise ValidationError(
                f"Invalid language '{language}'. Choose from: {valid_langs}"
            )

        normalized_files = normalize_files(files)
    except ValidationError as exc:
        return {
            "status": "error",
            "error_type": "ValidationError",
            "message": str(exc),
        }

    # --- 2. Client Pool Rotation ---
    # Try each available client once, no per-client retry
    attempted_clients = set()
    last_error = None
    total_clients = len(pool.clients)

    # Try up to total_clients times to ensure we attempt all available clients
    for _ in range(total_clients):
        client_id, client = pool.get_client()

        if client is None:
            # All clients are in backoff or none exist
            if not attempted_clients:
                earliest = pool.get_earliest_available_time()
                # Don't return error yet - try fallback first
                last_error = Exception(f"All clients are currently unavailable. Earliest available at: {earliest}")
            break  # Stop trying if no clients are available

        if client_id in attempted_clients:
            # Already tried this client, skip to avoid infinite loop
            continue

        attempted_clients.add(client_id)

        try:
            # Stateful Validation (Depends on client properties)
            validate_search_params(mode, model, chosen_sources, own_account=client.own)
            validate_query_limits(client.copilot, client.file_upload, mode, len(normalized_files))

            response = client.search(
                clean_query,
                mode=mode,
                model=model,
                sources=chosen_sources,
                files=normalized_files,
                stream=False,
                language=language,
                incognito=incognito,
            )

            # Success
            pool.mark_client_success(client_id)
            clean_result = extract_clean_result(response)
            return {"status": "ok", "data": clean_result}

        except ValidationError as exc:
            last_error = exc
            error_msg = str(exc).lower()
            # Heuristic: Is this a client-specific limitation or user error?
            is_client_limit = any(kw in error_msg for kw in ["pro", "limit", "account", "upload", "quota", "remaining"])

            if is_client_limit:
                # Client-specific limitation - mark failure and try next client
                if mode == "pro":
                    pool.mark_client_pro_failure(client_id)
                else:
                    pool.mark_client_failure(client_id)
                # Continue to next client
                continue
            else:
                # User input error (e.g. "Invalid model", "Invalid sources") - do not failover
                return {
                    "status": "error",
                    "error_type": "ValidationError",
                    "message": str(exc),
                }

        except Exception as exc:
            last_error = exc
            error_msg = str(exc).lower()

            # Check if it's a pro-related failure
            if mode == "pro" and any(kw in error_msg for kw in ["pro", "quota", "limit", "remaining"]):
                pool.mark_client_pro_failure(client_id)
            else:
                # General failure - mark and continue to next client
                pool.mark_client_failure(client_id)
            # Continue to next client
            continue

    # --- 3. Fallback to Anonymous Auto Mode ---
    # Use config setting if fallback_to_auto parameter is not explicitly set (True by default)
    # Check pool's fallback config for the actual setting
    should_fallback = fallback_to_auto and pool.is_fallback_to_auto_enabled()
    if should_fallback and mode != "auto":
        try:
            from ..logger import get_logger
            logger = get_logger("server.app")
            logger.info("All clients failed, attempting fallback to anonymous auto mode...")

            # Create anonymous client (no cookies)
            anonymous_client = Client({})
            response = anonymous_client.search(
                clean_query,
                mode="auto",
                model=None,  # auto mode doesn't support model selection
                sources=chosen_sources,
                files={},  # auto mode doesn't support file upload
                stream=False,
                language=language,
                incognito=True,
            )

            if response and "answer" in response:
                logger.info("Fallback to anonymous auto mode succeeded")
                clean_result = extract_clean_result(response)
                clean_result["fallback"] = True  # Mark as fallback result
                clean_result["fallback_mode"] = "auto"
                return {"status": "ok", "data": clean_result}
            else:
                logger.warning("Fallback to anonymous auto mode failed: no answer in response")
        except Exception as fallback_exc:
            from ..logger import get_logger
            logger = get_logger("server.app")
            logger.warning(f"Fallback to anonymous auto mode failed: {fallback_exc}")

    # --- 4. Final Error Handling ---
    return {
        "status": "error",
        "error_type": last_error.__class__.__name__ if last_error else "RequestFailed",
        "message": str(last_error) if last_error else "Request failed after multiple attempts.",
    }
