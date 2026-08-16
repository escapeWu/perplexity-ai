"""Server-backed chat sessions used only by the bundled WebUI."""

from __future__ import annotations

import asyncio
import json
import time
import uuid
from typing import Any, Dict, Optional, Union

from starlette.concurrency import iterate_in_threadpool
from starlette.requests import Request
from starlette.responses import JSONResponse, StreamingResponse

from .app import extract_clean_result, get_pool, mcp
from .oai import _create_error_response, _extract_files_from_messages, _verify_auth
from .progress import ProgressTracker, make_progress_chunk
from .session_runtime import CommittedTurn as _CommittedTurn
from .session_runtime import SessionChatError as WebUIChatError
from .session_runtime import run_session_non_stream as _run_session_non_stream
from .session_runtime import run_session_stream as _run_session_stream
from .session_runtime import stream_delta as _stream_delta
from .utils import parse_oai_model_with_thinking
from .webui_sessions import (
    InvalidWebUISession,
    WebUISession,
    WebUISessionNotFound,
    WebUISessionStore,
    get_webui_session_store,
)


def _session_error(exc: Exception) -> JSONResponse:
    if isinstance(exc, InvalidWebUISession):
        return _create_error_response(str(exc), "invalid_request_error", 400)
    if isinstance(exc, WebUISessionNotFound):
        return _create_error_response(str(exc), "invalid_request_error", 404)
    if isinstance(exc, WebUIChatError):
        return _create_error_response(str(exc), exc.error_type, exc.status_code)
    return _create_error_response(str(exc), "api_error", 500)


def _latest_user_message(messages: Any) -> Dict[str, Any]:
    if not isinstance(messages, list) or not messages:
        raise InvalidWebUISession("messages must contain the current user turn")
    for message in reversed(messages):
        if isinstance(message, dict) and message.get("role") == "user":
            content = message.get("content", "")
            if not isinstance(content, (str, list)):
                raise InvalidWebUISession(
                    "The current user message content must be a string or content-part array"
                )
            return message
    raise InvalidWebUISession("messages must contain a user message")


def _query_from_message(message: Dict[str, Any], *, has_files: bool) -> str:
    content = message.get("content", "")
    if isinstance(content, str):
        query = content.strip()
    else:
        query = " ".join(
            part.get("text", "").strip()
            for part in content
            if isinstance(part, dict)
            and part.get("type") == "text"
            and isinstance(part.get("text"), str)
            and part.get("text", "").strip()
        )
    if query:
        return query
    if has_files:
        return "Please analyze the attached file."
    raise InvalidWebUISession("The current user message cannot be empty")


async def _webui_stream_response(
    store: WebUISessionStore,
    session_id: str,
    *,
    user_message: Dict[str, Any],
    query: str,
    files: Dict[str, bytes],
    mode: str,
    model: Optional[str],
    model_id: str,
    response_id: str,
    created: int,
    include_progress: bool,
) -> StreamingResponse:
    async def event_generator():
        upstream = _run_session_stream(
            store,
            session_id,
            user_content=user_message.get("content", ""),
            query=query,
            files=files,
            mode=mode,
            model=model,
            model_id=model_id,
        )
        accumulated_content = ""
        latest_sources: list[Dict[str, Any]] = []
        committed_session: Optional[WebUISession] = None
        progress_tracker = ProgressTracker() if include_progress else None

        try:
            if progress_tracker is not None:
                for progress in progress_tracker.update(
                    {"text": [{"step_type": "INITIAL_QUERY", "content": {}}]}
                ):
                    progress_data = make_progress_chunk(response_id, created, model_id, progress)
                    yield f"data: {json.dumps(progress_data, ensure_ascii=False)}\n\n"

            async for item in iterate_in_threadpool(upstream):
                if isinstance(item, _CommittedTurn):
                    committed_session = item.session
                    continue

                if progress_tracker is not None:
                    for progress in progress_tracker.update(item):
                        progress_data = make_progress_chunk(
                            response_id, created, model_id, progress
                        )
                        yield f"data: {json.dumps(progress_data, ensure_ascii=False)}\n\n"

                clean_chunk = extract_clean_result(item)
                sources = clean_chunk.get("sources", [])
                if isinstance(sources, list) and sources:
                    latest_sources = sources
                answer = clean_chunk.get("answer", "")
                if not isinstance(answer, str):
                    continue
                delta, accumulated_content = _stream_delta(accumulated_content, answer)
                if not delta:
                    continue
                chunk_data = {
                    "id": response_id,
                    "object": "chat.completion.chunk",
                    "created": created,
                    "model": model_id,
                    "choices": [
                        {
                            "index": 0,
                            "delta": {"content": delta},
                            "finish_reason": None,
                        }
                    ],
                }
                yield f"data: {json.dumps(chunk_data, ensure_ascii=False)}\n\n"

            if committed_session is None:
                raise WebUIChatError("The session turn ended without being committed")
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
                "choices": [{"index": 0, "delta": {}, "finish_reason": "error"}],
                "error": {
                    "message": str(exc),
                    "type": getattr(exc, "error_type", "api_error"),
                },
            }
            yield f"data: {json.dumps(error_data, ensure_ascii=False)}\n\n"
            yield "data: [DONE]\n\n"
            return
        finally:
            close = getattr(upstream, "close", None)
            if close:
                try:
                    await asyncio.shield(asyncio.to_thread(close))
                except (RuntimeError, ValueError):
                    pass

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
            "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
            "sources": latest_sources,
            "webui_session": committed_session.to_public_dict(),
        }
        yield f"data: {json.dumps(final_data, ensure_ascii=False)}\n\n"
        yield "data: [DONE]\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@mcp.custom_route("/v1/webui/sessions", methods=["GET", "POST"])
async def webui_sessions(request: Request) -> JSONResponse:
    auth_error = _verify_auth(request)
    if auth_error:
        return auth_error

    store = get_webui_session_store()
    try:
        if request.method == "GET":
            sessions = [session.to_public_dict() for session in store.list_sessions()]
            return JSONResponse({"object": "list", "data": sessions})

        try:
            body = await request.json()
        except Exception:
            body = {}
        if not isinstance(body, dict):
            raise InvalidWebUISession("Request body must be an object")
        title = body.get("title")
        if title is not None and not isinstance(title, str):
            raise InvalidWebUISession("Session title must be a string")
        return JSONResponse(store.create_session(title).to_public_dict(), status_code=201)
    except Exception as exc:
        return _session_error(exc)


@mcp.custom_route("/v1/webui/sessions/{session_id}", methods=["GET", "PATCH", "DELETE"])
async def webui_session_detail(request: Request) -> JSONResponse:
    auth_error = _verify_auth(request)
    if auth_error:
        return auth_error

    store = get_webui_session_store()
    session_id = request.path_params.get("session_id", "")
    try:
        if request.method == "GET":
            session = store.get_session(session_id)
            return JSONResponse(session.to_public_dict(messages=store.get_messages(session_id)))
        if request.method == "DELETE":
            store.delete_session(session_id)
            return JSONResponse({"id": session_id, "deleted": True})

        try:
            body = await request.json()
        except Exception as exc:
            raise InvalidWebUISession("Invalid JSON body") from exc
        if not isinstance(body, dict) or "title" not in body:
            raise InvalidWebUISession("title is required")
        session = store.rename_session(session_id, body["title"])
        return JSONResponse(session.to_public_dict())
    except Exception as exc:
        return _session_error(exc)


@mcp.custom_route("/v1/webui/chat/completions", methods=["POST"])
async def webui_chat_completions(
    request: Request,
) -> Union[JSONResponse, StreamingResponse]:
    """Run one native Perplexity turn inside an immutable WebUI session."""
    auth_error = _verify_auth(request)
    if auth_error:
        return auth_error

    try:
        body = await request.json()
    except Exception:
        return _create_error_response("Invalid JSON body", "invalid_request_error", 400)
    if not isinstance(body, dict):
        return _create_error_response(
            "Request body must be an object", "invalid_request_error", 400
        )

    try:
        session_id = body.get("session_id")
        if not isinstance(session_id, str):
            raise InvalidWebUISession("session_id is required")
        store = get_webui_session_store()
        store.get_session(session_id)

        model_id = body.get("model")
        if not isinstance(model_id, str) or not model_id:
            raise InvalidWebUISession("model is required")
        stream = body.get("stream", True)
        if not isinstance(stream, bool):
            raise InvalidWebUISession("stream must be a boolean")
        thinking = body.get("thinking", False)
        if not isinstance(thinking, bool):
            raise InvalidWebUISession("thinking must be a boolean")
        options = body.get("perplexity", {})
        if not isinstance(options, dict):
            raise InvalidWebUISession("perplexity must be an object")
        include_progress = options.get("include_progress", False)
        if not isinstance(include_progress, bool):
            raise InvalidWebUISession("perplexity.include_progress must be a boolean")

        mode, model, effective_model_id = parse_oai_model_with_thinking(
            model_id,
            thinking,
            get_pool().get_model_subscription_tiers(),
        )
        user_message = _latest_user_message(body.get("messages"))
        try:
            files = await asyncio.to_thread(_extract_files_from_messages, [user_message])
        except LookupError as exc:
            return _create_error_response(str(exc), "invalid_request_error", 404)
        except ValueError as exc:
            return _create_error_response(str(exc), "invalid_request_error", 400)
        query = _query_from_message(user_message, has_files=bool(files))
    except ValueError as exc:
        return _create_error_response(str(exc), "invalid_request_error", 400)
    except Exception as exc:
        return _session_error(exc)

    response_id = f"chatcmpl-{uuid.uuid4().hex[:24]}"
    created = int(time.time())
    if stream:
        return await _webui_stream_response(
            store,
            session_id,
            user_message=user_message,
            query=query,
            files=files,
            mode=mode,
            model=model,
            model_id=effective_model_id,
            response_id=response_id,
            created=created,
            include_progress=include_progress,
        )

    try:
        data, committed = await asyncio.to_thread(
            _run_session_non_stream,
            store,
            session_id,
            user_content=user_message.get("content", ""),
            query=query,
            files=files,
            mode=mode,
            model=model,
            model_id=effective_model_id,
        )
    except Exception as exc:
        return _session_error(exc)

    answer = data.get("answer", "")
    sources = data.get("sources", [])
    prompt_tokens = len(query.split())
    completion_tokens = len(answer.split()) if isinstance(answer, str) else 0
    return JSONResponse(
        {
            "id": response_id,
            "object": "chat.completion",
            "created": created,
            "model": effective_model_id,
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": answer},
                    "finish_reason": "stop",
                }
            ],
            "usage": {
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "total_tokens": prompt_tokens + completion_tokens,
            },
            "sources": sources,
            "webui_session": committed.to_public_dict(),
        }
    )
