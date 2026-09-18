"""WebUI session CRUD and the compatibility completion adapter."""
from __future__ import annotations

import math

from starlette.requests import Request
from starlette.responses import JSONResponse

from .app import get_job_runtime, get_pool, mcp
from .chat_input import latest_user_message as _latest_user_message, message_text, parse_chat_body, read_json, submit_chat
from .job_responses import completion_response
from .job_store import public_job
from .oai import _verify_auth, _session_error_response, _create_error_response
from .webui_sessions import InvalidWebUISession, get_webui_session_store, validate_session_id

_session_error = _session_error_response


def _query_from_message(message, *, has_files=False):
    query = message_text(message.get("content", "")).strip()
    if query:
        return query
    if has_files:
        return "Please analyze the attached file."
    raise InvalidWebUISession("The current user message cannot be empty")


async def _webui_stream_response(store, session_id, *, user_message, query, files, mode,
                                 model, model_id, response_id, created, include_progress):
    runtime = await get_job_runtime(store)
    job = await runtime.submit(session_id=session_id, query=query, files=files, mode=mode,
                               model=model, model_id=model_id, user_content=user_message.get("content", ""))
    return await completion_response(runtime, job, include_progress=include_progress, webui=True,
                                     response_id=response_id, created=created)


@mcp.custom_route("/v1/webui/sessions", methods=["GET", "POST"])
async def webui_sessions(request: Request):
    error = _verify_auth(request)
    if error:
        return error
    try:
        runtime = await get_job_runtime()
        store = runtime.sessions
        if request.method == "POST":
            body = await read_json(request)
            session = await runtime.db(store.create_session, body.get("title"))
            return JSONResponse(session.to_public_dict(), status_code=201)
        limit = min(200, max(1, int(request.query_params.get("limit", 50))))
        cursor = request.query_params.get("before")
        before = None
        if cursor:
            timestamp, session_id = cursor.split("|", 1)
            value = float(timestamp)
            if not math.isfinite(value):
                raise ValueError("Invalid pagination cursor")
            before = (value, validate_session_id(session_id))
        sessions = await runtime.db(store.list_sessions, limit=limit + 1, before=before)
        more = len(sessions) > limit
        sessions = sessions[:limit]
        active = await runtime.db(runtime.store.list, active=True, limit=200)
        jobs_by_session = {job["session_id"]: public_job(job) for job in active}
        return JSONResponse({"object": "list", "data": [
            {**session.to_public_dict(), "active_job": jobs_by_session.get(session.id)} for session in sessions],
            "has_more": more, "next_cursor": f"{sessions[-1].updated_at}|{sessions[-1].id}" if more else None})
    except Exception as exc:
        return _session_error(exc)


@mcp.custom_route("/v1/webui/sessions/{session_id}", methods=["GET", "PATCH", "DELETE"])
async def webui_session_detail(request: Request):
    error = _verify_auth(request)
    if error:
        return error
    session_id = request.path_params.get("session_id", "")
    try:
        runtime = await get_job_runtime()
        store = runtime.sessions
        if request.method == "DELETE":
            await runtime.db(store.delete_session, session_id)
            return JSONResponse({"id": session_id, "deleted": True})
        if request.method == "PATCH":
            body = await read_json(request)
            session = await runtime.db(store.rename_session, session_id, body.get("title"))
            return JSONResponse(session.to_public_dict())
        session = await runtime.db(store.get_session, session_id)
        limit = min(200, max(1, int(request.query_params.get("limit", 50))))
        cursor = request.query_params.get("before")
        before = int(cursor) if cursor else None
        messages = await runtime.db(store.get_messages, session_id, limit=limit, before=before)
        more = bool(messages) and await runtime.db(store.has_messages_before, session_id, messages[0]["id"])
        jobs = await runtime.db(runtime.store.list, session_id=session_id, limit=1, include_snapshot=True)
        return JSONResponse({**session.to_public_dict(messages=messages), "has_more": more,
            "next_cursor": messages[0]["id"] if more else None,
            "latest_job": public_job(jobs[0], snapshot=True) if jobs else None})
    except Exception as exc:
        return _session_error(exc)


@mcp.custom_route("/v1/webui/chat/completions", methods=["POST"])
async def webui_chat_completions(request: Request):
    error = _verify_auth(request)
    if error:
        return error
    try:
        body = await read_json(request)
        if not isinstance(body.get("session_id"), str):
            raise InvalidWebUISession("session_id is required")
        runtime = await get_job_runtime()
        job = await submit_chat(body, runtime, idempotency_key=request.headers.get("idempotency-key"))
        stream = body.get("stream", True)
        progress = body.get("perplexity", {}).get("include_progress", False)
        body.clear()
        return await completion_response(runtime, job, stream=stream,
            include_progress=progress, webui=True, request=request)
    except Exception as exc:
        return _session_error(exc)
