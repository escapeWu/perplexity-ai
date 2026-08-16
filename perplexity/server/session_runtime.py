"""Shared native Perplexity conversation runtime for WebUI, OAI, and MCP."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Iterable, Iterator, List, Optional, Union

from ..model_registry import get_model_registry
from .app import extract_clean_result, get_pool, run_query, run_query_stream
from .webui_sessions import (
    InvalidWebUISession,
    WebUISession,
    WebUISessionStore,
)

FileInput = Union[Dict[str, Any], Iterable[str]]


class SessionChatError(Exception):
    """Error safe to expose through a session-enabled public API."""

    def __init__(self, message: str, *, status_code: int = 502, error_type: str = "api_error"):
        super().__init__(message)
        self.status_code = status_code
        self.error_type = error_type


@dataclass(frozen=True)
class CommittedTurn:
    """Marker emitted after a streamed turn has been committed atomically."""

    session: WebUISession


def stream_delta(previous: str, current: str) -> tuple[str, str]:
    """Convert cumulative upstream answer snapshots into append-only deltas."""
    if not current or current == previous:
        return "", previous
    if current.startswith(previous):
        return current[len(previous) :], current
    if previous.startswith(current):
        return "", previous

    # Some upstream variants emit independent fragments instead of cumulative
    # snapshots. Preserve those fragments as append-only content.
    return current, previous + current


def get_or_create_session(
    store: WebUISessionStore,
    session_id: Optional[str],
    *,
    origin: str,
) -> WebUISession:
    """Resolve a supplied session or create a new server-owned conversation."""
    if session_id is None:
        return store.create_session(origin=origin)
    if not isinstance(session_id, str) or not session_id:
        raise InvalidWebUISession("session_id must be a non-empty string when provided")
    return store.get_session(session_id)


def claim_account(
    store: WebUISessionStore,
    session: WebUISession,
    mode: str,
    model: Optional[str],
) -> WebUISession:
    """Bind one compatible healthy pool account before the first request."""
    if session.client_id:
        return session

    pool = get_pool()
    required_tier = get_model_registry().required_tier(mode, model)
    excluded_ids: set[str] = set()
    pro_mode = mode in {"pro", "reasoning", "deep research"}

    for _ in range(max(1, len(pool.clients))):
        client_id, client = pool.get_client(
            exclude_ids=excluded_ids,
            required_tier=required_tier,
        )
        if client_id is None or client is None:
            break
        if pro_mode and pool.get_client_state(client_id) == "downgrade":
            excluded_ids.add(client_id)
            continue

        store.bind_client_once(session.id, client_id)
        return store.get_session(session.id)

    raise SessionChatError(
        "No healthy account is available for this session and model.",
        status_code=503,
        error_type="service_unavailable",
    )


def cursor_from_data(data: Dict[str, Any]) -> tuple[str, List[str]]:
    """Validate and unpack the internal native follow-up cursor."""
    follow_up = data.get("_follow_up")
    if not isinstance(follow_up, dict):
        raise SessionChatError("Upstream response did not include a native follow-up cursor")
    backend_uuid = follow_up.get("backend_uuid")
    attachments = follow_up.get("attachments", [])
    if not isinstance(backend_uuid, str) or not backend_uuid.strip():
        raise SessionChatError("Upstream response did not include a native follow-up cursor")
    if not isinstance(attachments, list) or not all(
        isinstance(attachment, str) for attachment in attachments
    ):
        raise SessionChatError("Upstream response included invalid follow-up attachments")
    return backend_uuid, attachments


def query_error(result: Dict[str, Any]) -> SessionChatError:
    """Map the shared query envelope to a stable session API error."""
    message = result.get("message", "Session request failed")
    error_type = result.get("error_type", "api_error")
    if error_type == "ValidationError":
        return SessionChatError(message, status_code=400, error_type="invalid_request_error")
    if "bound account" in str(message).lower() or error_type == "NoAvailableClients":
        return SessionChatError(message, status_code=503, error_type="service_unavailable")
    return SessionChatError(message)


def run_session_non_stream(
    store: WebUISessionStore,
    session_id: str,
    *,
    user_content: Any,
    query: str,
    files: FileInput,
    mode: str,
    model: Optional[str],
    model_id: str,
    search_sources: Optional[List[str]] = None,
    language: str = "en-US",
    incognito: bool = False,
) -> tuple[Dict[str, Any], WebUISession]:
    """Execute and atomically commit one non-streaming native conversation turn."""
    with store.turn_lock(session_id):
        session = claim_account(store, store.get_session(session_id), mode, model)
        result = run_query(
            query,
            mode,
            model,
            search_sources,
            language,
            incognito,
            files,
            False,
            session.client_id,
            session.follow_up(),
            True,
        )
        if result.get("status") != "ok":
            raise query_error(result)

        data = result.get("data", {})
        if not isinstance(data, dict):
            raise SessionChatError("Upstream response was not an object")
        backend_uuid, attachments = cursor_from_data(data)
        answer = data.get("answer", "")
        if not isinstance(answer, str):
            answer = str(answer)
            data["answer"] = answer
        result_sources = data.get("sources", [])
        committed = store.commit_turn(
            session_id,
            user_content=user_content,
            assistant_content=answer,
            sources=result_sources,
            backend_uuid=backend_uuid,
            attachments=attachments,
            model=model_id,
        )
        return data, committed


def run_session_stream(
    store: WebUISessionStore,
    session_id: str,
    *,
    user_content: Any,
    query: str,
    files: FileInput,
    mode: str,
    model: Optional[str],
    model_id: str,
    search_sources: Optional[List[str]] = None,
    language: str = "en-US",
    incognito: bool = False,
) -> Iterator[Union[Dict[str, Any], CommittedTurn]]:
    """Hold the session lock until a streamed turn fully commits or is closed."""
    with store.turn_lock(session_id):
        session = claim_account(store, store.get_session(session_id), mode, model)
        upstream = run_query_stream(
            query,
            mode,
            model,
            search_sources,
            language,
            incognito,
            files,
            False,
            session.client_id,
            session.follow_up(),
        )
        accumulated_answer = ""
        latest_sources: List[Dict[str, Any]] = []
        latest_follow_up: Optional[Dict[str, Any]] = None
        try:
            for upstream_chunk in upstream:
                clean_chunk = extract_clean_result(upstream_chunk)
                answer = clean_chunk.get("answer", "")
                if isinstance(answer, str):
                    _, accumulated_answer = stream_delta(accumulated_answer, answer)
                result_sources = clean_chunk.get("sources", [])
                if isinstance(result_sources, list) and result_sources:
                    latest_sources = result_sources
                if isinstance(upstream_chunk.get("_follow_up"), dict):
                    latest_follow_up = upstream_chunk["_follow_up"]
                yield upstream_chunk

            backend_uuid, attachments = cursor_from_data({"_follow_up": latest_follow_up})
            committed = store.commit_turn(
                session_id,
                user_content=user_content,
                assistant_content=accumulated_answer,
                sources=latest_sources,
                backend_uuid=backend_uuid,
                attachments=attachments,
                model=model_id,
            )
            yield CommittedTurn(committed)
        finally:
            close = getattr(upstream, "close", None)
            if close:
                close()
