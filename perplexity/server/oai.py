"""
OpenAI-compatible API endpoints.
Provides /v1/models and /v1/chat/completions routes.
"""

import asyncio
import json
import time
import uuid
from typing import Optional, Union

from starlette.requests import Request
from starlette.responses import JSONResponse, StreamingResponse

from .utils import (
    generate_oai_models, parse_oai_model, create_oai_error_response,
)

try:
    from .app import mcp, run_query, MCP_TOKEN, get_pool
except ImportError:
    from perplexity.server.app import mcp, run_query, MCP_TOKEN, get_pool

# If mcp is None (e.g. testing env), create a dummy decorator
if mcp is None:
    class DummyMCP:
        def custom_route(self, *args, **kwargs):
            def decorator(func):
                return func
            return decorator
    mcp = DummyMCP()


def _verify_auth(request: Request) -> Optional[JSONResponse]:
    """Verify Authorization header. Returns error response if invalid, None if valid."""
    auth = request.headers.get("authorization") or request.headers.get("Authorization")
    if auth != f"Bearer {MCP_TOKEN}":
        return _create_error_response(
            "Unauthorized: Invalid or missing Bearer token",
            "authentication_error",
            401
        )
    return None


def _create_error_response(message: str, error_type: str, status_code: int) -> JSONResponse:
    """Create standardized OpenAI-format error response."""
    return JSONResponse(
        create_oai_error_response(message, error_type),
        status_code=status_code
    )


async def _non_stream_chat_response(
    query: str,
    mode: str,
    model: Optional[str],
    model_id: str,
    response_id: str,
    created: int,
    fallback_to_auto: bool = True
) -> JSONResponse:
    """Generate non-streaming chat completion response."""
    # Call run_query in thread pool
    pool = get_pool()
    incognito = pool.is_incognito_enabled()
    result = await asyncio.to_thread(
        run_query, query, mode, model, None, "en-US", incognito, None, fallback_to_auto
    )

    if result.get("status") == "error":
        error_msg = result.get("message", "Unknown error")
        error_type = result.get("error_type", "api_error")
        if error_type == "NoAvailableClients":
            return _create_error_response(error_msg, "service_unavailable", 503)
        return _create_error_response(error_msg, "api_error", 500)

    data = result.get("data", {})
    answer = data.get("answer", "")
    sources = data.get("sources", [])

    # Approximate token counts
    prompt_tokens = len(query.split())
    completion_tokens = len(answer.split())

    return JSONResponse({
        "id": response_id,
        "object": "chat.completion",
        "created": created,
        "model": model_id,
        "choices": [{
            "index": 0,
            "message": {
                "role": "assistant",
                "content": answer
            },
            "finish_reason": "stop"
        }],
        "usage": {
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": prompt_tokens + completion_tokens
        },
        "sources": sources
    })


async def _fake_stream_chat_response(
    query: str,
    mode: str,
    model: Optional[str],
    model_id: str,
    response_id: str,
    created: int,
    fallback_to_auto: bool = True
) -> StreamingResponse:
    """Generate fake streaming SSE response.

    First fetches the complete result, then streams it character by character.
    """

    async def event_generator():
        # First, get the complete result
        result = await asyncio.to_thread(
            run_query, query, mode, model, None, "en-US", False, None, fallback_to_auto
        )

        if result.get("status") == "error":
            # Send error as final chunk
            error_data = {
                "id": response_id,
                "object": "chat.completion.chunk",
                "created": created,
                "model": model_id,
                "choices": [{
                    "index": 0,
                    "delta": {},
                    "finish_reason": "error"
                }]
            }
            yield f"data: {json.dumps(error_data)}\n\n"
            yield "data: [DONE]\n\n"
            return

        data = result.get("data", {})
        answer = data.get("answer", "")
        sources = data.get("sources", [])

        # Stream the answer character by character
        for char in answer:
            chunk_data = {
                "id": response_id,
                "object": "chat.completion.chunk",
                "created": created,
                "model": model_id,
                "choices": [{
                    "index": 0,
                    "delta": {"content": char},
                    "finish_reason": None
                }]
            }
            yield f"data: {json.dumps(chunk_data, ensure_ascii=False)}\n\n"

        # Send final chunk with finish_reason and sources
        final_data = {
            "id": response_id,
            "object": "chat.completion.chunk",
            "created": created,
            "model": model_id,
            "choices": [{
                "index": 0,
                "delta": {},
                "finish_reason": "stop"
            }],
            "sources": sources
        }
        yield f"data: {json.dumps(final_data)}\n\n"
        yield "data: [DONE]\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
        }
    )


# ==================== OpenAI-Compatible API Endpoints ====================

@mcp.custom_route("/v1/models", methods=["GET"])
async def oai_list_models(request: Request) -> JSONResponse:
    """OpenAI-compatible models list endpoint."""
    # Verify authentication
    auth_error = _verify_auth(request)
    if auth_error:
        return auth_error

    models = generate_oai_models()
    return JSONResponse({
        "object": "list",
        "data": models
    })


@mcp.custom_route("/v1/chat/completions", methods=["POST"])
async def oai_chat_completions(request: Request) -> Union[JSONResponse, StreamingResponse]:
    """OpenAI-compatible chat completions endpoint.

    Supports both streaming and non-streaming modes.
    Note: Streaming mode uses fake streaming (fetches complete result first,
    then streams character by character).
    """
    # Verify authentication
    auth_error = _verify_auth(request)
    if auth_error:
        return auth_error

    # Parse request body
    try:
        body = await request.json()
    except Exception:
        return _create_error_response("Invalid JSON body", "invalid_request_error", 400)

    # Validate required fields
    model_id = body.get("model")
    messages = body.get("messages", [])
    stream = body.get("stream", False)

    if not model_id:
        return _create_error_response("model is required", "invalid_request_error", 400)

    if not messages:
        return _create_error_response("messages is required", "invalid_request_error", 400)

    # Parse model to get mode and internal model
    try:
        mode, model = parse_oai_model(model_id)
    except ValueError as e:
        return _create_error_response(str(e), "invalid_request_error", 400)

    # Build query from all messages (concatenate history into a single query)
    query_parts = []
    for msg in messages:
        role = msg.get("role", "")
        content = msg.get("content", "")
        if isinstance(content, list):
            # Handle array content (text parts)
            content = " ".join(
                part.get("text", "") for part in content
                if isinstance(part, dict) and part.get("type") == "text"
            )
        if content:
            if role == "system":
                query_parts.append(f"[System]: {content}")
            elif role == "user":
                query_parts.append(f"[User]: {content}")
            elif role == "assistant":
                query_parts.append(f"[Assistant]: {content}")

    if not query_parts:
        return _create_error_response("No messages found", "invalid_request_error", 400)

    query = "\n\n".join(query_parts)

    # Generate response ID and timestamp
    response_id = f"chatcmpl-{uuid.uuid4().hex[:24]}"
    created = int(time.time())

    if stream:
        return await _fake_stream_chat_response(query, mode, model, model_id, response_id, created)
    else:
        return await _non_stream_chat_response(query, mode, model, model_id, response_id, created)
