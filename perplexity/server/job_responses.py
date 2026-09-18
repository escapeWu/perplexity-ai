"""HTTP output adapters for a single durable job; no upstream execution here."""
from __future__ import annotations

import asyncio
import json
import time
from contextlib import suppress

import anyio
from starlette.responses import JSONResponse, StreamingResponse

from .job_store import JobError, TERMINAL
from ..exceptions import ValidationError
from .progress import make_progress_chunk


def job_failure(job):
    error = job.get("error") or {}
    code = error.get("code", "job_" + job["state"])
    status = {"upstream_rate_limited": 429, "account_unavailable": 503}.get(code,
        504 if job["state"] == "timed_out" else 409 if job["state"] == "cancelled" else 502)
    return JobError(error.get("message", "Task ended with state: " + job["state"]), code, status,
                    job_id=job.get("id", job.get("job_id")))


def error_response(exc):
    invalid = isinstance(exc, (ValueError, ValidationError))
    code = getattr(exc, "error_type", "invalid_request_error" if invalid else "api_error")
    status = getattr(exc, "status_code", 400 if invalid else 500)
    message = str(exc) if invalid or isinstance(exc, JobError) or hasattr(exc, "error_type") else "Request failed"
    return JSONResponse({"error": {"message": message, "type": code, **getattr(exc, "details", {})}}, status_code=status,
                        headers={"Retry-After": "1"} if status == 429 else None)


class JobStreamingResponse(StreamingResponse):
    def __init__(self, iterator, runtime, job_id, *, cancel_on_disconnect=False):
        self.runtime, self.job_id = runtime, job_id
        self.cancel_on_disconnect = cancel_on_disconnect
        super().__init__(iterator, media_type="text/event-stream", headers={
            "Cache-Control": "no-cache", "X-Accel-Buffering": "no", "X-Job-ID": job_id,
        })

    async def __call__(self, scope, receive, send):
        try:
            await super().__call__(scope, receive, send)
        finally:
            with anyio.CancelScope(shield=True):
                close = getattr(self.body_iterator, "aclose", None)
                if close:
                    await close()
                if self.cancel_on_disconnect:
                    await self.runtime.cancel(self.job_id)


async def wait_request_job(runtime, job_id, request=None):
    waiter = asyncio.create_task(runtime.wait(job_id))
    watcher = None
    try:
        if request is None:
            return await waiter
        async def disconnected():
            while not await request.is_disconnected():
                await asyncio.sleep(0.1)
        watcher = asyncio.create_task(disconnected())
        done, _ = await asyncio.wait({waiter, watcher}, return_when=asyncio.FIRST_COMPLETED)
        if waiter in done:
            return waiter.result()
        await runtime.cancel(job_id)
        raise JobError("Client disconnected", "client_disconnected", 499)
    except asyncio.CancelledError:
        with anyio.CancelScope(shield=True):
            await runtime.cancel(job_id)
        raise
    finally:
        for task in (waiter, watcher):
            if task and not task.done():
                task.cancel()
        await asyncio.gather(*[t for t in (waiter, watcher) if t], return_exceptions=True)


def completion_payload(job, response_id, created, *, webui=False):
    if job["state"] != "completed":
        raise job_failure(job)
    result = job["snapshot"]
    answer = result["answer"]
    prompt_tokens = len(job["payload"]["query"].split())
    completion_tokens = len(answer.split())
    payload = {"id": response_id, "object": "chat.completion", "created": created,
               "model": job["payload"]["model_id"], "job_id": job["id"], "session_id": job["session_id"],
               "choices": [{"index": 0, "message": {"role": "assistant", "content": answer}, "finish_reason": "stop"}],
               "sources": result.get("sources", []),
               "usage": {"prompt_tokens": prompt_tokens, "completion_tokens": completion_tokens,
                         "total_tokens": prompt_tokens + completion_tokens}}
    if webui:
        payload["webui_session"] = result.get("session")
    return payload


async def completion_response(runtime, job, *, stream=True, include_progress=False,
                              webui=False, request=None, response_id=None, created=None):
    response_id = response_id or "chatcmpl-" + job["id"][4:]
    created = int(time.time()) if created is None else created
    if not stream:
        try:
            final = await wait_request_job(runtime, job["id"], request)
            return JSONResponse(completion_payload(final, response_id, created, webui=webui),
                                headers={"X-Job-ID": job["id"], "X-Session-ID": job["session_id"]})
        except JobError as exc:
            return error_response(exc)

    async def generate():
        previous = ""
        progress_seen = {}
        base = {"id": response_id, "object": "chat.completion.chunk", "created": created,
                "model": job["payload"]["model_id"], "job_id": job["id"], "session_id": job["session_id"]}
        def encode(data):
            return "data: " + json.dumps(data, ensure_ascii=False) + "\n\n"
        events = runtime.events(job["id"])
        try:
            async for event in events:
                if event["type"] == "heartbeat":
                    yield ": keepalive\n\n"
                    continue
                current_job = event.get("job")
                snapshot = current_job.get("snapshot", {}) if current_job else event.get("data", {})
                if event["type"] == "delta":
                    answer = previous + snapshot.get("content", "")
                else:
                    answer = snapshot.get("answer", previous)
                if not answer.startswith(previous):
                    raise JobError("Upstream revised emitted text; retrieve the authoritative task result",
                                   "answer_revised", 502, job_id=job["id"])
                if include_progress:
                    for progress in snapshot.get("progress", []):
                        if progress_seen.get(progress.get("id")) != progress:
                            progress_seen[progress.get("id")] = progress
                            yield encode({**make_progress_chunk(response_id, created, base["model"], progress),
                                          "job_id": job["id"], "session_id": job["session_id"]})
                delta = answer[len(previous):]
                previous = answer
                if delta:
                    yield encode({**base, "choices": [{"index": 0, "delta": {"content": delta}, "finish_reason": None}]})
                if event["type"] == "terminal":
                    if current_job["state"] != "completed":
                        raise job_failure(current_job)
                    final = {**base, "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
                             "sources": snapshot.get("sources", [])}
                    if webui:
                        final["webui_session"] = snapshot.get("session")
                    yield encode(final)
                    yield "data: [DONE]\n\n"
                    return
            raise JobError("Task stream ended before a terminal state", "upstream_incomplete", 502)
        except JobError as exc:
            yield encode({**base, "choices": [{"index": 0, "delta": {}, "finish_reason": "error"}],
                          "error": {"message": str(exc), "type": exc.code, **exc.details}})
            yield "data: [DONE]\n\n"
        finally:
            with anyio.CancelScope(shield=True):
                await events.aclose()
                await runtime.cancel(job["id"])

    response = JobStreamingResponse(generate(), runtime, job["id"], cancel_on_disconnect=True)
    response.headers["X-Session-ID"] = job["session_id"]
    return response
