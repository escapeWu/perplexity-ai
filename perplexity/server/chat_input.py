"""Shared chat input validation for WebUI, OAI and detached Jobs."""
from __future__ import annotations

import asyncio
import anyio
import json
from concurrent.futures import ThreadPoolExecutor

from .file_sources import extract_files
from .job_store import JobError
from .files_store import attachment_input_budget
from .utils import parse_oai_model_with_thinking
from .webui_sessions import validate_session_id

MAX_JSON_BYTES = 32 * 1024 * 1024
_file_executor = None
_file_pending = set()


async def read_json(request):
    length = request.headers.get("content-length")
    if length and int(length) > MAX_JSON_BYTES:
        raise JobError("Request body exceeds 32 MiB", "request_too_large", 413)
    body = bytearray()
    async for chunk in request.stream():
        if len(body) + len(chunk) > MAX_JSON_BYTES:
            raise JobError("Request body exceeds 32 MiB", "request_too_large", 413)
        body.extend(chunk)
    try:
        value = json.loads(body)
    except (ValueError, UnicodeDecodeError) as exc:
        raise ValueError("Invalid JSON body") from exc
    if not isinstance(value, dict):
        raise ValueError("Request body must be an object")
    return value


def latest_user_message(messages):
    if not isinstance(messages, list) or not messages or len(messages) > 200:
        raise ValueError("messages must contain 1..200 entries including a user message")
    for message in reversed(messages):
        if isinstance(message, dict) and message.get("role") == "user":
            if not isinstance(message.get("content", ""), (str, list)):
                raise ValueError("Message content must be a string or array")
            return message
    raise ValueError("messages must contain a user message")


def message_text(content):
    if isinstance(content, str):
        return content
    return " ".join(part.get("text", "") for part in content
                    if isinstance(part, dict) and part.get("type") == "text"
                    and isinstance(part.get("text"), str)) if isinstance(content, list) else ""


def query_from_messages(messages):
    labels = {"user": "User", "assistant": "Assistant", "system": "System"}
    return "\n\n".join(f"[{labels[msg['role']]}]: {message_text(msg.get('content'))}"
                       for msg in messages if isinstance(msg, dict) and msg.get("role") in labels
                       and message_text(msg.get("content")))


def has_attachments(messages):
    return isinstance(messages, list) and any(
        isinstance(message, dict) and isinstance(message.get("content"), list)
        and any(isinstance(part, dict) and part.get("type") == "input_file" for part in message["content"])
        for message in messages)


async def resolve_files(messages):
    global _file_executor
    # Ordinary text requests must never wait behind slow attachment downloads.
    if not has_attachments(messages):
        return {}
    if _file_executor is None:
        _file_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="file-input")
    if len(_file_pending) >= 16:
        raise JobError("File input queue is full", "queue_full", 429)
    future = asyncio.get_running_loop().run_in_executor(_file_executor, extract_files, messages)
    _file_pending.add(future)
    def done(f):
        _file_pending.discard(f)
        if not f.cancelled():
            f.exception()
    future.add_done_callback(done)
    try:
        return await asyncio.shield(future)
    except asyncio.CancelledError:
        with anyio.CancelScope(shield=True):
            try:
                await asyncio.shield(future)
            except Exception:
                pass
        raise


async def submit_chat(body, runtime, *, origin="webui", detached=False, idempotency_key=None):
    async with attachment_input_budget(has_attachments(body.get("messages"))):
        inputs = await parse_chat_body(body, runtime.pool, origin=origin)
        try:
            return await runtime.submit(**inputs, detached=detached, idempotency_key=idempotency_key)
        finally:
            inputs.clear()


async def close_file_inputs():
    global _file_executor
    executor, _file_executor = _file_executor, None
    if executor is not None:
        executor.shutdown(wait=False, cancel_futures=True)
    if _file_pending:
        await asyncio.gather(*list(_file_pending), return_exceptions=True)


async def parse_chat_body(body, pool, *, origin="webui"):
    model_id, messages = body.get("model"), body.get("messages")
    if not isinstance(model_id, str) or not model_id:
        raise ValueError("model is required")
    user = latest_user_message(messages)
    session_id = body.get("session_id")
    if session_id is not None:
        validate_session_id(session_id)
    for field in ("stream", "thinking"):
        if field in body and not isinstance(body[field], bool):
            raise ValueError(f"{field} must be a boolean")
    if body.get("reasoning_effort") is not None:
        raise ValueError("reasoning_effort is unsupported; use thinking=true")
    options = body.get("perplexity", {})
    if not isinstance(options, dict) or not isinstance(options.get("include_progress", False), bool):
        raise ValueError("perplexity.include_progress must be a boolean")
    mode, model, effective_id = parse_oai_model_with_thinking(model_id, body.get("thinking", False), pool.get_model_subscription_tiers())
    flatten = origin == "oai" and session_id is None
    files = await resolve_files(messages if flatten else [user])
    query = query_from_messages(messages) if flatten else message_text(user.get("content", "")).strip()
    if not query and files:
        query = "Please analyze the attached file."
    if not query:
        raise ValueError("The current user message cannot be empty")
    return {"query": query, "mode": mode, "model": model, "model_id": effective_id,
            "session_id": session_id, "user_content": user.get("content", ""),
            "files": files, "origin": origin}
