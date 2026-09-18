"""Shared HTTP/SSE validation and bounded final-result assembly."""
from __future__ import annotations

import json
from typing import Any

from .response_parser import UpstreamResponseAccumulator

MAX_RESPONSE_BYTES = 1024 * 1024


class UpstreamError(Exception):
    """A safe, classified error; never includes response bodies or credentials."""

    def __init__(self, message: str, code: str = "upstream_error", *, status: int = 502,
                 retry_after: float = 0):
        super().__init__(message)
        self.code = code
        self.status = status
        self.retry_after = retry_after


def check_http_status(status: int, headers: Any) -> None:
    if status >= 400 or status < 200 or status >= 300:
        code = "upstream_rate_limited" if status == 429 else "upstream_http_error"
        if status in (401, 403):
            code = "account_unavailable"
        try:
            retry = min(3600, max(1, float(headers.get("retry-after", 1))))
        except (ValueError, TypeError):
            retry = 60
        raise UpstreamError(f"Upstream returned HTTP {status}", code,
                            status=429 if status == 429 else 503 if status in (401, 403) else 502,
                            retry_after=retry if status == 429 else 0)


def check_response(status: int, headers: Any) -> None:
    check_http_status(status, headers)
    if str(headers.get("content-type", "")).split(";", 1)[0].strip().lower() != "text/event-stream":
        raise UpstreamError("Upstream did not return an event stream", "upstream_protocol_error")


class SSEDecoder:
    """Incremental SSE framing, including LF/CRLF and multiline data fields."""

    def __init__(self, limit: int = MAX_RESPONSE_BYTES):
        self.buffer = b""
        self.event = "message"
        self.data: list[bytes] = []
        self.size = 0
        self.limit = limit

    def feed(self, chunk: bytes) -> list[tuple[str, str]]:
        self.buffer += chunk
        if len(self.buffer) + self.size > self.limit:
            raise UpstreamError("Upstream event exceeded the buffer budget", "buffer_limit")
        events = []
        while b"\n" in self.buffer:
            line, self.buffer = self.buffer.split(b"\n", 1)
            line = line.rstrip(b"\r")
            if not line:
                if self.data or self.event != "message":
                    try:
                        events.append((self.event, b"\n".join(self.data).decode("utf-8")))
                    except UnicodeDecodeError as exc:
                        raise UpstreamError("Invalid SSE encoding", "upstream_protocol_error") from exc
                self.event, self.data, self.size = "message", [], 0
            elif line.startswith(b"event:"):
                self.event = line[6:].strip().decode("ascii", errors="replace")
            elif line.startswith(b"data:"):
                value = line[5:]
                self.data.append(value[1:] if value.startswith(b" ") else value)
                self.size += len(value)
        return events


class ResponseState:
    """One latest snapshot, never a list of cumulative response snapshots."""

    def __init__(self, attachments: list[str] | None = None):
        self.accumulator = UpstreamResponseAccumulator()
        self.latest: dict[str, Any] = {}
        self.ended = False
        self.attachments = list(attachments or [])

    def feed(self, event: str, text: str) -> dict[str, Any] | None:
        if event == "end_of_stream" or text.strip() == "[DONE]":
            self.ended = True
            return None
        if event in ("error", "failure"):
            raise UpstreamError("Upstream reported a failed generation", "upstream_failed")
        if event != "message":
            return None
        try:
            data = json.loads(text)
        except (TypeError, ValueError) as exc:
            raise UpstreamError("Invalid upstream event JSON", "upstream_protocol_error") from exc
        if not isinstance(data, dict):
            raise UpstreamError("Invalid upstream event object", "upstream_protocol_error")
        if data.get("error") or str(data.get("status", "")).upper() in ("FAILED", "ERROR", "CANCELLED"):
            raise UpstreamError("Upstream reported a failed generation", "upstream_failed")
        legacy = data.get("text")
        if isinstance(legacy, str) and legacy:
            try:
                data["text"] = json.loads(legacy)
            except ValueError:
                pass
        if isinstance(data.get("text"), list):
            for step in data["text"]:
                if isinstance(step, dict) and step.get("step_type") == "FINAL":
                    answer = step.get("content", {}).get("answer")
                    if isinstance(answer, str):
                        try:
                            answer = json.loads(answer)
                        except ValueError:
                            answer = {"answer": answer}
                    if isinstance(answer, dict):
                        for key in ("answer", "chunks"):
                            if key in answer:
                                data[key] = answer[key]
        data = self.accumulator.normalize(data)
        # Empty terminal metadata must not erase an answer/source snapshot.
        for key, value in data.items():
            if key in ("answer", "chunks") and not value and self.latest.get(key):
                continue
            self.latest[key] = value
        answer = self.latest.get("answer", "")
        if not isinstance(answer, str):
            raise UpstreamError("Upstream answer is not text", "upstream_protocol_error")
        if len(answer.encode("utf-8")) > MAX_RESPONSE_BYTES:
            raise UpstreamError("Upstream answer exceeded the output budget", "output_limit")
        backend = self.latest.get("backend_uuid")
        if isinstance(backend, str) and backend.strip():
            self.latest["_follow_up"] = {"backend_uuid": backend, "attachments": self.attachments}
        if len(json.dumps(self.latest, ensure_ascii=False).encode()) > 4 * MAX_RESPONSE_BYTES:
            raise UpstreamError("Upstream metadata exceeded the snapshot budget", "output_limit")
        return dict(self.latest)

    def finish(self) -> dict[str, Any]:
        if not self.ended:
            raise UpstreamError("Upstream stream ended without its terminal event", "upstream_incomplete")
        status = self.latest.get("status")
        if status and status != "COMPLETED":
            raise UpstreamError("Upstream did not complete the generation", "upstream_incomplete")
        if not self.latest.get("answer", "").strip():
            raise UpstreamError("Upstream completed without an answer", "empty_answer")
        return dict(self.latest)


def clean_result(response: dict[str, Any]) -> dict[str, Any]:
    result = {key: response[key] for key in (
        "answer", "display_model", "user_selected_model", "model_downgraded",
        "requested_model", "effective_model",
    ) if key in response}
    candidates = response.get("chunks", [])
    for step in response.get("text", []) if isinstance(response.get("text"), list) else []:
        if isinstance(step, dict) and step.get("step_type") == "SEARCH_RESULTS":
            candidates = step.get("content", {}).get("web_results", []) or candidates
    result["sources"] = [
        {"url": item["url"], "title": item.get("title", item.get("name", ""))}
        for item in candidates if isinstance(item, dict) and isinstance(item.get("url"), str)
    ] if isinstance(candidates, list) else []
    return result
