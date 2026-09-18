"""Detached task API: submission, observation, complete result and explicit cancellation."""
import asyncio
import json
import math

from starlette.requests import Request
from starlette.responses import JSONResponse

from .app import get_job_runtime, mcp
from .chat_input import read_json, submit_chat
from .job_responses import JobStreamingResponse, error_response, job_failure
from .job_store import JobError, TERMINAL, public_job
from .oai import _verify_auth, _session_error_response


@mcp.custom_route("/v1/jobs", methods=["GET", "POST"])
async def jobs(request: Request):
    error = _verify_auth(request)
    if error:
        return error
    try:
        runtime = await get_job_runtime()
        if request.method == "GET":
            limit = min(200, max(1, int(request.query_params.get("limit", 50))))
            rows = await runtime.db(runtime.store.list, session_id=request.query_params.get("session_id"),
                active=request.query_params.get("active") == "true", limit=limit + 1,
                before=request.query_params.get("before"))
            more = len(rows) > limit
            rows = rows[:limit]
            cursor = f"{rows[-1]['created_at']}|{rows[-1]['id']}" if rows and more else None
            return JSONResponse({"object": "list", "data": [public_job(row) for row in rows],
                                 "has_more": more, "next_cursor": cursor})
        body = await read_json(request)
        job = await submit_chat(body, runtime, detached=True, idempotency_key=request.headers.get("idempotency-key"))
        return JSONResponse({**public_job(job), "events_url": f"/v1/jobs/{job['id']}/events",
                             "result_url": f"/v1/jobs/{job['id']}/result"}, status_code=202)
    except Exception as exc:
        return _session_error_response(exc)


@mcp.custom_route("/v1/jobs/{job_id}", methods=["GET"])
async def job_detail(request: Request):
    error = _verify_auth(request)
    if error:
        return error
    try:
        runtime = await get_job_runtime()
        job = await runtime.get(request.path_params["job_id"])
        return JSONResponse(public_job(job, snapshot=request.query_params.get("include_output") == "true"))
    except Exception as exc:
        return error_response(exc)


@mcp.custom_route("/v1/jobs/{job_id}/result", methods=["GET"])
async def job_result(request: Request):
    error = _verify_auth(request)
    if error:
        return error
    try:
        wait = float(request.query_params.get("wait_seconds", 0))
        if not math.isfinite(wait) or not 0 <= wait <= 30:
            raise ValueError("wait_seconds must be between 0 and 30")
        runtime = await get_job_runtime()
        job = await runtime.get(request.path_params["job_id"])
        if wait and job["state"] not in TERMINAL:
            try:
                job = await asyncio.wait_for(runtime.wait(job["id"]), wait)
            except asyncio.TimeoutError:
                job = await runtime.get(job["id"])
        if job["state"] not in TERMINAL:
            return JSONResponse(public_job(job), status_code=202, headers={"Retry-After": "1"})
        if job["state"] != "completed":
            raise job_failure(job)
        return JSONResponse({**public_job(job), "result": job["snapshot"]})
    except Exception as exc:
        return error_response(exc)


@mcp.custom_route("/v1/jobs/{job_id}/cancel", methods=["POST"])
async def job_cancel(request: Request):
    error = _verify_auth(request)
    if error:
        return error
    try:
        runtime = await get_job_runtime()
        job = await runtime.cancel(request.path_params["job_id"])
        return JSONResponse(public_job(job), status_code=202 if job["state"] == "cancelling" else 200)
    except Exception as exc:
        return error_response(exc)


@mcp.custom_route("/v1/jobs/{job_id}/events", methods=["GET"])
async def job_events(request: Request):
    error = _verify_auth(request)
    if error:
        return error
    try:
        runtime = await get_job_runtime()
        job_id = request.path_params["job_id"]
        job = await runtime.get(job_id)
        cursor = request.query_params.get("after", request.headers.get("last-event-id", "0"))
        if ":" in cursor:
            cursor_job, cursor = cursor.split(":", 1)
            if cursor_job != job_id:
                raise ValueError("Event cursor belongs to another task")
        after = int(cursor)
        if not 0 <= after <= job["seq"]:
            raise ValueError("Invalid event cursor")
    except Exception as exc:
        return error_response(exc)

    async def generate():
        events = runtime.events(job_id, after=after)
        try:
            async for event in events:
                if event["type"] == "heartbeat":
                    yield ": keepalive\n\n"
                else:
                    yield f"id: {job_id}:{event['seq']}\nevent: {event['type']}\ndata: {json.dumps(event, ensure_ascii=False)}\n\n"
        finally:
            await events.aclose()
    return JobStreamingResponse(generate(), runtime, job_id)
