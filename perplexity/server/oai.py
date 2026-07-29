"""
OpenAI-compatible API endpoints.
Provides /v1/models, /v1/chat/completions, and /v1/files routes.
"""

import asyncio
import base64
import json
import os
import time
import uuid
from typing import Dict, Optional, Union

from starlette.concurrency import iterate_in_threadpool
from starlette.requests import Request
from starlette.responses import JSONResponse, StreamingResponse

from .utils import (
    generate_oai_models, parse_oai_model, create_oai_error_response,
)
from .files_store import FileEntry, get_files_store
from .progress import ProgressTracker, make_progress_chunk

try:
    from .app import (
        MCP_TOKEN,
        extract_clean_result,
        get_pool,
        mcp,
        run_query,
        run_query_stream,
    )
except ImportError:
    from perplexity.server.app import (
        MCP_TOKEN,
        extract_clean_result,
        get_pool,
        mcp,
        run_query,
        run_query_stream,
    )

try:
    from ..config import ALLOWED_FILE_EXTENSIONS
except ImportError:
    from perplexity.config import ALLOWED_FILE_EXTENSIONS

# If mcp is None (e.g. testing env), create a dummy decorator
if mcp is None:
    class DummyMCP:
        def custom_route(self, *args, **kwargs):
            def decorator(func):
                return func
            return decorator
    mcp = DummyMCP()


# ==================== Auth & Error Helpers ====================

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


# ==================== File Validation & Resolution ====================

def _validate_extension(filename: str) -> None:
    """Raise ValueError if filename extension is not in the whitelist."""
    _, ext = os.path.splitext(filename.lower())
    if not ext or ext not in ALLOWED_FILE_EXTENSIONS:
        raise ValueError(
            f"Unsupported file extension '{ext}' for '{filename}'. "
            f"Supported types include documents, code, images, audio, and video files."
        )


def _resolve_input_file(part: dict) -> tuple[str, bytes]:
    """
    Resolve a single input_file content part to (filename, bytes).

    Dispatches to one of three handlers based on which key is present:
    - file_data + filename: base64-encoded inline content
    - file_url: remote URL to download
    - file_id: reference to a previously uploaded file
    """
    if "file_data" in part:
        return _resolve_file_data(part)
    elif "file_url" in part:
        return _resolve_file_url(part)
    elif "file_id" in part:
        return _resolve_file_id(part)
    else:
        raise ValueError("input_file part must contain file_data, file_url, or file_id")


def _resolve_file_data(part: dict) -> tuple[str, bytes]:
    """Decode base64 inline file content."""
    filename = part.get("filename", "").strip()
    if not filename:
        raise ValueError("input_file with file_data must include a non-empty filename")

    raw = part.get("file_data", "")
    # Strip data-URL prefix if present: "data:<mime>;base64,<data>"
    if isinstance(raw, str) and raw.startswith("data:"):
        if ";base64," in raw:
            raw = raw.split(";base64,", 1)[1]
        else:
            raise ValueError("file_data data-URL must use base64 encoding")

    try:
        data = base64.b64decode(raw)
    except Exception:
        raise ValueError(f"file_data for '{filename}' is not valid base64")

    _validate_extension(filename)
    return filename, data


def _resolve_file_url(part: dict) -> tuple[str, bytes]:
    """Download file from a remote URL."""
    url = part.get("file_url", "").strip()
    if not url:
        raise ValueError("file_url must be a non-empty string")

    # Derive filename from URL path, stripping query string
    path_part = url.split("?")[0].split("/")[-1]
    filename = path_part if path_part else "file"

    _validate_extension(filename)

    try:
        from curl_cffi import requests as curl_requests
        resp = curl_requests.get(url, timeout=30)
        if not resp.ok:
            raise ValueError(f"Failed to fetch file_url '{url}': HTTP {resp.status_code}")
        data = resp.content
    except ValueError:
        raise
    except Exception as e:
        raise ValueError(f"Failed to fetch file_url '{url}': {e}")

    return filename, data


def _resolve_file_id(part: dict) -> tuple[str, bytes]:
    """Look up a previously uploaded file by its ID."""
    file_id = part.get("file_id", "").strip()
    if not file_id:
        raise ValueError("file_id must be a non-empty string")

    store = get_files_store()
    entry = store.get(file_id)
    if entry is None:
        raise LookupError(f"file_id '{file_id}' not found")

    return entry.filename, entry.data


def _extract_files_from_messages(messages: list) -> Dict[str, bytes]:
    """
    Collect all input_file parts from all messages and resolve them to {filename: bytes}.
    Raises ValueError / LookupError on invalid parts.
    """
    files: Dict[str, bytes] = {}
    for msg in messages:
        content = msg.get("content", "")
        if not isinstance(content, list):
            continue
        for part in content:
            if not isinstance(part, dict) or part.get("type") != "input_file":
                continue
            filename, data = _resolve_input_file(part)
            files[filename] = data
    return files


# ==================== Chat Response Helpers ====================

async def _non_stream_chat_response(
    query: str,
    mode: str,
    model: Optional[str],
    model_id: str,
    response_id: str,
    created: int,
    files: Optional[Dict[str, bytes]] = None,
    fallback_to_auto: bool = True
) -> JSONResponse:
    """Generate non-streaming chat completion response."""
    pool = get_pool()
    incognito = pool.is_incognito_enabled()
    result = await asyncio.to_thread(
        run_query, query, mode, model, None, "en-US", incognito, files or {}, fallback_to_auto
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


def _stream_delta(previous: str, current: str) -> tuple[str, str]:
    """Convert cumulative upstream answer snapshots into append-only deltas."""
    if not current or current == previous:
        return "", previous
    if current.startswith(previous):
        return current[len(previous) :], current
    if previous.startswith(current):
        return "", previous

    # Some upstream variants may emit independent fragments instead of
    # cumulative snapshots. Preserve those fragments as append-only content.
    return current, previous + current


async def _stream_chat_response(
    query: str,
    mode: str,
    model: Optional[str],
    model_id: str,
    response_id: str,
    created: int,
    files: Optional[Dict[str, bytes]] = None,
    fallback_to_auto: bool = True,
    include_progress: bool = False,
) -> StreamingResponse:
    """Forward the upstream Perplexity stream as OpenAI-compatible SSE."""

    async def event_generator():
        upstream = run_query_stream(
            query,
            mode,
            model,
            None,
            "en-US",
            False,
            files or {},
            fallback_to_auto,
        )
        accumulated_content = ""
        latest_sources = []
        progress_tracker = ProgressTracker() if include_progress else None

        try:
            async for upstream_chunk in iterate_in_threadpool(upstream):
                if progress_tracker is not None:
                    for progress in progress_tracker.update(upstream_chunk):
                        progress_data = make_progress_chunk(
                            response_id, created, model_id, progress
                        )
                        yield f"data: {json.dumps(progress_data, ensure_ascii=False)}\n\n"

                clean_chunk = extract_clean_result(upstream_chunk)
                sources = clean_chunk.get("sources", [])
                if sources:
                    latest_sources = sources

                answer = clean_chunk.get("answer", "")
                delta, accumulated_content = _stream_delta(
                    accumulated_content, answer
                )
                if not delta:
                    continue

                chunk_data = {
                    "id": response_id,
                    "object": "chat.completion.chunk",
                    "created": created,
                    "model": model_id,
                    "choices": [{
                        "index": 0,
                        "delta": {"content": delta},
                        "finish_reason": None
                    }]
                }
                yield f"data: {json.dumps(chunk_data, ensure_ascii=False)}\n\n"
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            if progress_tracker is not None:
                failed_progress = progress_tracker.finish("failed")
                if failed_progress is not None:
                    progress_data = make_progress_chunk(
                        response_id, created, model_id, failed_progress
                    )
                    yield f"data: {json.dumps(progress_data, ensure_ascii=False)}\n\n"

            error_data = {
                "id": response_id,
                "object": "chat.completion.chunk",
                "created": created,
                "model": model_id,
                "choices": [{
                    "index": 0,
                    "delta": {},
                    "finish_reason": "error"
                }],
                "error": {
                    "message": str(exc),
                    "type": "api_error",
                },
            }
            yield f"data: {json.dumps(error_data, ensure_ascii=False)}\n\n"
            yield "data: [DONE]\n\n"
            return
        finally:
            close = getattr(upstream, "close", None)
            if close:
                await asyncio.shield(asyncio.to_thread(close))

        if progress_tracker is not None:
            completed_progress = progress_tracker.finish("completed")
            if completed_progress is not None:
                progress_data = make_progress_chunk(
                    response_id, created, model_id, completed_progress
                )
                yield f"data: {json.dumps(progress_data, ensure_ascii=False)}\n\n"

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
            "sources": latest_sources
        }
        yield f"data: {json.dumps(final_data)}\n\n"
        yield "data: [DONE]\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        }
    )


# ==================== OpenAI-Compatible API Endpoints ====================

@mcp.custom_route("/v1/models", methods=["GET"])
async def oai_list_models(request: Request) -> JSONResponse:
    """OpenAI-compatible models list endpoint."""
    auth_error = _verify_auth(request)
    if auth_error:
        return auth_error

    models = generate_oai_models()
    return JSONResponse({
        "object": "list",
        "data": models
    })


@mcp.custom_route("/v1/files", methods=["POST"])
async def oai_upload_file(request: Request) -> JSONResponse:
    """Upload a file for use in chat completions via file_id."""
    auth_error = _verify_auth(request)
    if auth_error:
        return auth_error

    try:
        form = await request.form()
    except Exception:
        return _create_error_response("Invalid multipart form data", "invalid_request_error", 400)

    upload = form.get("file")
    if upload is None:
        return _create_error_response("Missing 'file' field in form data", "invalid_request_error", 400)

    filename = getattr(upload, "filename", None) or "upload"
    try:
        _validate_extension(filename)
    except ValueError as e:
        return _create_error_response(str(e), "invalid_request_error", 400)

    data = await upload.read()
    purpose = form.get("purpose", "assistants")
    if isinstance(purpose, bytes):
        purpose = purpose.decode()

    file_id = f"file-{uuid.uuid4().hex}"
    entry = FileEntry(
        id=file_id,
        filename=filename,
        data=data,
        size=len(data),
        created_at=int(time.time()),
        purpose=str(purpose),
    )
    store = get_files_store()
    store.put(entry)

    return JSONResponse(store.to_file_object(entry))


@mcp.custom_route("/v1/files/{file_id}", methods=["GET"])
async def oai_get_file(request: Request) -> JSONResponse:
    """Retrieve metadata for an uploaded file."""
    auth_error = _verify_auth(request)
    if auth_error:
        return auth_error

    file_id = request.path_params.get("file_id", "")
    store = get_files_store()
    entry = store.get(file_id)
    if entry is None:
        return _create_error_response(f"File '{file_id}' not found", "invalid_request_error", 404)

    return JSONResponse(store.to_file_object(entry))


@mcp.custom_route("/v1/files/{file_id}", methods=["DELETE"])
async def oai_delete_file(request: Request) -> JSONResponse:
    """Delete an uploaded file."""
    auth_error = _verify_auth(request)
    if auth_error:
        return auth_error

    file_id = request.path_params.get("file_id", "")
    store = get_files_store()
    deleted = store.delete(file_id)
    if not deleted:
        return _create_error_response(f"File '{file_id}' not found", "invalid_request_error", 404)

    return JSONResponse({"id": file_id, "object": "file", "deleted": True})


@mcp.custom_route("/v1/chat/completions", methods=["POST"])
async def oai_chat_completions(request: Request) -> Union[JSONResponse, StreamingResponse]:
    """OpenAI-compatible chat completions endpoint.

    Streams upstream events by default. Pass stream=false to wait for a complete
    JSON response. Accepts input_file content parts (file_data, file_url, file_id).
    Streaming clients may opt into progress chunks with perplexity.include_progress.
    """
    auth_error = _verify_auth(request)
    if auth_error:
        return auth_error

    try:
        body = await request.json()
    except Exception:
        return _create_error_response("Invalid JSON body", "invalid_request_error", 400)

    model_id = body.get("model")
    messages = body.get("messages", [])
    stream = body.get("stream", True)
    perplexity_options = body.get("perplexity", {})

    if not model_id:
        return _create_error_response("model is required", "invalid_request_error", 400)

    if not messages:
        return _create_error_response("messages is required", "invalid_request_error", 400)
    if not isinstance(stream, bool):
        return _create_error_response(
            "stream must be a boolean", "invalid_request_error", 400
        )
    if not isinstance(perplexity_options, dict):
        return _create_error_response(
            "perplexity must be an object", "invalid_request_error", 400
        )
    include_progress = perplexity_options.get("include_progress", False)
    if not isinstance(include_progress, bool):
        return _create_error_response(
            "perplexity.include_progress must be a boolean",
            "invalid_request_error",
            400,
        )

    try:
        mode, model = parse_oai_model(model_id)
    except ValueError as e:
        return _create_error_response(str(e), "invalid_request_error", 400)

    # Extract files from input_file content parts
    try:
        files = await asyncio.to_thread(_extract_files_from_messages, messages)
    except LookupError as e:
        return _create_error_response(str(e), "invalid_request_error", 404)
    except ValueError as e:
        return _create_error_response(str(e), "invalid_request_error", 400)

    # Build query text from messages (skip input_file parts)
    query_parts = []
    for msg in messages:
        role = msg.get("role", "")
        content = msg.get("content", "")
        if isinstance(content, list):
            # Extract only text parts; input_file parts are handled separately
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
    response_id = f"chatcmpl-{uuid.uuid4().hex[:24]}"
    created = int(time.time())

    if stream:
        return await _stream_chat_response(
            query,
            mode,
            model,
            model_id,
            response_id,
            created,
            files,
            include_progress=include_progress,
        )
    else:
        return await _non_stream_chat_response(
            query, mode, model, model_id, response_id, created, files
        )
