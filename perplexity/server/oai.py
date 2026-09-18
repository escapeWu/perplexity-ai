"""OpenAI-compatible HTTP adapters over the shared durable job runtime."""
import asyncio
import time
import uuid
from typing import Any, Dict, Optional

from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.formparsers import MultiPartException

from .app import MCP_TOKEN, get_pool, get_job_runtime, mcp
from .chat_input import (
    latest_user_message as _latest_user_message, message_text as _message_text,
    query_from_messages as _query_from_messages, parse_chat_body, read_json, submit_chat,
)
from .file_sources import (
    validate_extension as _validate_extension, resolve_input_file as _resolve_input_file,
    resolve_file_data as _resolve_file_data, resolve_file_url as _resolve_file_url,
    resolve_file_id as _resolve_file_id, extract_files as _extract_files_from_messages,
)
from .files_store import FileEntry, MAX_FILE_BYTES, get_files_store, attachment_input_budget
from .job_responses import completion_response, error_response
from .job_store import JobError
from .session_runtime import stream_delta as _stream_delta
from .utils import create_oai_error_response, generate_oai_models
from .webui_sessions import InvalidWebUISession, WebUISessionNotFound, SessionBusy


def _verify_auth(request):
    if request.headers.get("authorization") != f"Bearer {MCP_TOKEN}":
        return _create_error_response("Unauthorized: Invalid or missing Bearer token", "authentication_error", 401)
    return None


def _create_error_response(message, error_type, status_code, *, session_id=None):
    payload = create_oai_error_response(message, error_type)
    if session_id is not None:
        payload["session_id"] = session_id
    return JSONResponse(payload, status_code=status_code)


def _session_error_response(exc, session_id=None):
    if isinstance(exc, (WebUISessionNotFound, LookupError)):
        return _create_error_response(str(exc), "invalid_request_error", 404, session_id=session_id)
    if isinstance(exc, InvalidWebUISession):
        return _create_error_response(str(exc), "invalid_request_error", 400, session_id=session_id)
    return error_response(exc)


async def _non_stream_chat_response(query, mode, model, model_id, response_id, created,
                                   files=None, fallback_to_auto=True, *, session_store=None,
                                   session_id=None, user_content=None):
    runtime = await get_job_runtime(session_store)
    try:
        job = await runtime.submit(query=query, mode=mode, model=model, model_id=model_id,
                                   files=files, session_id=session_id, user_content=user_content, origin="oai")
        return await completion_response(runtime, job, stream=False, response_id=response_id, created=created)
    except Exception as exc:
        return _session_error_response(exc, session_id)


async def _stream_chat_response(query, mode, model, model_id, response_id, created,
                               files=None, fallback_to_auto=True, include_progress=False, *,
                               session_store=None, session_id=None, user_content=None):
    runtime = await get_job_runtime(session_store)
    try:
        job = await runtime.submit(query=query, mode=mode, model=model, model_id=model_id,
                                   files=files, session_id=session_id, user_content=user_content, origin="oai")
        return await completion_response(runtime, job, include_progress=include_progress,
                                         response_id=response_id, created=created)
    except Exception as exc:
        return _session_error_response(exc, session_id)


@mcp.custom_route("/v1/models", methods=["GET"])
async def oai_list_models(request: Request):
    error = _verify_auth(request)
    if error:
        return error
    return JSONResponse({"object": "list", "data": generate_oai_models(get_pool().get_model_subscription_tiers())})


@mcp.custom_route("/v1/chat/completions", methods=["POST"])
async def oai_chat_completions(request: Request):
    error = _verify_auth(request)
    if error:
        return error
    try:
        body = await read_json(request)
        runtime = await get_job_runtime()
        job = await submit_chat(body, runtime, origin="oai", idempotency_key=request.headers.get("idempotency-key"))
        stream = body.get("stream", True)
        progress = body.get("perplexity", {}).get("include_progress", False)
        body.clear()
        return await completion_response(runtime, job, stream=stream,
            include_progress=progress, request=request)
    except Exception as exc:
        return _session_error_response(exc)


@mcp.custom_route("/v1/files", methods=["POST"])
async def oai_upload_file(request: Request):
    error = _verify_auth(request)
    if error:
        return error
    try:
        async with attachment_input_budget():
            return await _upload_file(request)
    except JobError as exc:
        return error_response(exc)


async def _upload_file(request):
    received, exceeded = 0, False
    receive = request._receive
    async def bounded_receive():
        nonlocal received, exceeded
        message = await receive()
        received += len(message.get("body", b""))
        if received > MAX_FILE_BYTES + 1024 * 1024:
            exceeded = True
            raise MultiPartException("Upload exceeds request limit")
        return message
    request._receive = bounded_receive
    form = None
    try:
        form = await request.form(max_files=1, max_fields=4, max_part_size=MAX_FILE_BYTES)
        upload = form.get("file")
        if upload is None or not hasattr(upload, "read"):
            raise ValueError("Missing file field")
        filename = upload.filename or "upload"
        _validate_extension(filename)
        data = bytearray()
        while True:
            chunk = await upload.read(65536)
            if not chunk:
                break
            if len(data) + len(chunk) > MAX_FILE_BYTES:
                raise JobError("File exceeds 20 MiB limit", "file_too_large", 413)
            data.extend(chunk)
        entry = FileEntry("file-" + uuid.uuid4().hex, filename, bytes(data), len(data),
                          int(time.time()), str(form.get("purpose", "assistants")))
        store = get_files_store()
        await asyncio.to_thread(store.put, entry)
        return JSONResponse(store.to_file_object(entry))
    except Exception as exc:
        if exceeded:
            return _create_error_response("Upload exceeds request limit", "file_too_large", 413)
        return error_response(exc if isinstance(exc, (ValueError, JobError)) else ValueError("Invalid multipart form data"))
    finally:
        if form is not None:
            await form.close()


@mcp.custom_route("/v1/files/{file_id}", methods=["GET"])
async def oai_get_file(request: Request):
    error = _verify_auth(request)
    if error:
        return error
    store = get_files_store()
    entry = await asyncio.to_thread(store.get, request.path_params.get("file_id", ""))
    if entry is None:
        return _create_error_response("File is missing or expired", "invalid_request_error", 404)
    return JSONResponse(store.to_file_object(entry))


@mcp.custom_route("/v1/files/{file_id}", methods=["DELETE"])
async def oai_delete_file(request: Request):
    error = _verify_auth(request)
    if error:
        return error
    file_id = request.path_params.get("file_id", "")
    try:
        deleted = await asyncio.to_thread(get_files_store().delete, file_id)
    except ValueError as exc:
        return _create_error_response(str(exc), "file_in_use", 409)
    if not deleted:
        return _create_error_response("File not found", "invalid_request_error", 404)
    return JSONResponse({"id": file_id, "object": "file", "deleted": True})
