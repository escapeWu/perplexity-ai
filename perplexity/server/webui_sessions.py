"""Durable, server-owned chat sessions shared by WebUI, OAI, and MCP callers."""

from __future__ import annotations

import json
import os
import re
import sqlite3
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional
from uuid import uuid4

DEFAULT_SESSION_TITLE = "New chat"
MAX_SESSION_TITLE_LENGTH = 120
SESSION_ID_PATTERN = re.compile(r"^sess_[0-9a-f]{32}$")
SESSION_ORIGINS = frozenset({"webui", "oai", "mcp"})


class WebUISessionError(Exception):
    """Base error for shared session operations."""


class WebUISessionNotFound(WebUISessionError):
    """Raised when a requested session does not exist."""


class InvalidWebUISession(WebUISessionError):
    """Raised when session input is malformed."""


@dataclass(frozen=True)
class WebUISession:
    id: str
    title: str
    title_is_custom: bool
    client_id: Optional[str]
    backend_uuid: Optional[str]
    attachments: List[str]
    model: Optional[str]
    origin: str
    created_at: float
    updated_at: float

    def to_public_dict(self, *, messages: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
        result: Dict[str, Any] = {
            "id": self.id,
            "title": self.title,
            "bound_client_id": self.client_id,
            "model": self.model,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }
        if messages is not None:
            result["messages"] = messages
        return result

    def follow_up(self) -> Optional[Dict[str, Any]]:
        if not self.backend_uuid:
            return None
        return {
            "backend_uuid": self.backend_uuid,
            "attachments": list(self.attachments),
        }


def validate_session_id(session_id: str) -> str:
    if not isinstance(session_id, str) or not SESSION_ID_PATTERN.fullmatch(session_id):
        raise InvalidWebUISession("Invalid session id")
    return session_id


def validate_session_title(title: str) -> str:
    if not isinstance(title, str):
        raise InvalidWebUISession("Session title must be a string")
    clean_title = " ".join(title.split())
    if not clean_title:
        raise InvalidWebUISession("Session title cannot be empty")
    if len(clean_title) > MAX_SESSION_TITLE_LENGTH:
        raise InvalidWebUISession(
            f"Session title is too long (max {MAX_SESSION_TITLE_LENGTH} characters)"
        )
    return clean_title


def sanitize_message_content(content: Any) -> Any:
    """Remove file payloads and private URLs before persisting display history."""
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        raise InvalidWebUISession("Message content must be a string or content-part array")

    safe_parts: List[Dict[str, str]] = []
    for part in content:
        if not isinstance(part, dict):
            continue
        part_type = part.get("type")
        if part_type == "text" and isinstance(part.get("text"), str):
            safe_parts.append({"type": "text", "text": part["text"]})
        elif part_type == "input_file":
            filename = part.get("filename")
            if not isinstance(filename, str) or not filename.strip():
                filename = "attachment"
            safe_parts.append({"type": "input_file", "filename": filename.strip()})
    return safe_parts


def _title_from_content(content: Any) -> str:
    if isinstance(content, str):
        text = content
    elif isinstance(content, list):
        text = " ".join(
            part.get("text", "")
            for part in content
            if isinstance(part, dict) and part.get("type") == "text"
        )
    else:
        text = ""
    text = " ".join(text.split()) or DEFAULT_SESSION_TITLE
    return text if len(text) <= 48 else f"{text[:47].rstrip()}…"


class WebUISessionStore:
    """SQLite-backed shared session store with immutable account affinity."""

    def __init__(self, database_path: str | Path):
        self.database_path = Path(database_path)
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self._locks_guard = threading.Lock()
        self._turn_locks: Dict[str, threading.Lock] = {}
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(str(self.database_path), timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.execute("PRAGMA journal_mode = WAL")
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS webui_sessions (
                    id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    title_is_custom INTEGER NOT NULL DEFAULT 0,
                    client_id TEXT,
                    backend_uuid TEXT,
                    attachments_json TEXT NOT NULL DEFAULT '[]',
                    model TEXT,
                    origin TEXT NOT NULL DEFAULT 'webui',
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL
                );

                CREATE TABLE IF NOT EXISTS webui_messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL,
                    role TEXT NOT NULL CHECK (role IN ('user', 'assistant')),
                    content_json TEXT NOT NULL,
                    sources_json TEXT NOT NULL DEFAULT '[]',
                    created_at REAL NOT NULL,
                    FOREIGN KEY (session_id) REFERENCES webui_sessions(id) ON DELETE CASCADE
                );

                CREATE INDEX IF NOT EXISTS idx_webui_sessions_updated
                    ON webui_sessions(updated_at DESC);
                CREATE INDEX IF NOT EXISTS idx_webui_messages_session
                    ON webui_messages(session_id, id);
                """
            )
            columns = {
                row["name"]
                for row in connection.execute("PRAGMA table_info(webui_sessions)").fetchall()
            }
            if "origin" not in columns:
                connection.execute(
                    "ALTER TABLE webui_sessions ADD COLUMN origin TEXT NOT NULL DEFAULT 'webui'"
                )
            connection.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_webui_sessions_origin_updated
                ON webui_sessions(origin, updated_at DESC)
                """
            )

    @staticmethod
    def _session_from_row(row: sqlite3.Row) -> WebUISession:
        try:
            attachments = json.loads(row["attachments_json"])
        except (TypeError, json.JSONDecodeError):
            attachments = []
        if not isinstance(attachments, list):
            attachments = []
        attachments = [item for item in attachments if isinstance(item, str)]
        return WebUISession(
            id=row["id"],
            title=row["title"],
            title_is_custom=bool(row["title_is_custom"]),
            client_id=row["client_id"],
            backend_uuid=row["backend_uuid"],
            attachments=attachments,
            model=row["model"],
            origin=row["origin"],
            created_at=float(row["created_at"]),
            updated_at=float(row["updated_at"]),
        )

    def create_session(
        self,
        title: Optional[str] = None,
        *,
        origin: str = "webui",
    ) -> WebUISession:
        if origin not in SESSION_ORIGINS:
            raise InvalidWebUISession(f"Invalid session origin: {origin}")
        session_id = f"sess_{uuid4().hex}"
        clean_title = validate_session_title(title) if title is not None else DEFAULT_SESSION_TITLE
        now = time.time()
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO webui_sessions (
                    id, title, title_is_custom, origin, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (session_id, clean_title, int(title is not None), origin, now, now),
            )
        return self.get_session(session_id)

    def list_sessions(self, *, origin: Optional[str] = "webui") -> List[WebUISession]:
        if origin is not None and origin not in SESSION_ORIGINS:
            raise InvalidWebUISession(f"Invalid session origin: {origin}")
        with self._connect() as connection:
            if origin is None:
                rows = connection.execute(
                    "SELECT * FROM webui_sessions ORDER BY updated_at DESC, created_at DESC"
                ).fetchall()
            else:
                rows = connection.execute(
                    """
                    SELECT * FROM webui_sessions
                    WHERE origin = ?
                    ORDER BY updated_at DESC, created_at DESC
                    """,
                    (origin,),
                ).fetchall()
        return [self._session_from_row(row) for row in rows]

    def get_session(self, session_id: str) -> WebUISession:
        validate_session_id(session_id)
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM webui_sessions WHERE id = ?", (session_id,)
            ).fetchone()
        if row is None:
            raise WebUISessionNotFound("Session not found")
        return self._session_from_row(row)

    def get_messages(self, session_id: str) -> List[Dict[str, Any]]:
        self.get_session(session_id)
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT role, content_json, sources_json, created_at
                FROM webui_messages
                WHERE session_id = ?
                ORDER BY id ASC
                """,
                (session_id,),
            ).fetchall()

        messages: List[Dict[str, Any]] = []
        for row in rows:
            try:
                content = json.loads(row["content_json"])
            except (TypeError, json.JSONDecodeError):
                content = ""
            try:
                sources = json.loads(row["sources_json"])
            except (TypeError, json.JSONDecodeError):
                sources = []
            message: Dict[str, Any] = {
                "role": row["role"],
                "content": content,
                "created_at": float(row["created_at"]),
            }
            if row["role"] == "assistant" and isinstance(sources, list) and sources:
                message["sources"] = sources
            messages.append(message)
        return messages

    def rename_session(self, session_id: str, title: str) -> WebUISession:
        validate_session_id(session_id)
        clean_title = validate_session_title(title)
        with self._connect() as connection:
            cursor = connection.execute(
                """
                UPDATE webui_sessions
                SET title = ?, title_is_custom = 1, updated_at = ?
                WHERE id = ?
                """,
                (clean_title, time.time(), session_id),
            )
        if cursor.rowcount == 0:
            raise WebUISessionNotFound("Session not found")
        return self.get_session(session_id)

    def delete_session(self, session_id: str) -> None:
        validate_session_id(session_id)
        with self._connect() as connection:
            cursor = connection.execute("DELETE FROM webui_sessions WHERE id = ?", (session_id,))
        if cursor.rowcount == 0:
            raise WebUISessionNotFound("Session not found")
        with self._locks_guard:
            self._turn_locks.pop(session_id, None)

    def bind_client_once(self, session_id: str, client_id: str) -> str:
        validate_session_id(session_id)
        if not isinstance(client_id, str) or not client_id.strip():
            raise InvalidWebUISession("Client id cannot be empty")
        clean_client_id = client_id.strip()

        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT client_id FROM webui_sessions WHERE id = ?", (session_id,)
            ).fetchone()
            if row is None:
                raise WebUISessionNotFound("Session not found")
            bound_client_id = row["client_id"]
            if bound_client_id is None:
                connection.execute(
                    "UPDATE webui_sessions SET client_id = ?, updated_at = ? WHERE id = ?",
                    (clean_client_id, time.time(), session_id),
                )
                bound_client_id = clean_client_id
        return str(bound_client_id)

    def commit_turn(
        self,
        session_id: str,
        *,
        user_content: Any,
        assistant_content: str,
        sources: Optional[List[Dict[str, Any]]],
        backend_uuid: str,
        attachments: List[str],
        model: Optional[str],
    ) -> WebUISession:
        validate_session_id(session_id)
        safe_user_content = sanitize_message_content(user_content)
        if not isinstance(assistant_content, str):
            raise InvalidWebUISession("Assistant content must be a string")
        if not isinstance(backend_uuid, str) or not backend_uuid.strip():
            raise InvalidWebUISession("Upstream response did not include a backend_uuid")
        if not isinstance(attachments, list) or not all(
            isinstance(item, str) for item in attachments
        ):
            raise InvalidWebUISession("Upstream attachments must be a list of strings")
        safe_sources = sources if isinstance(sources, list) else []
        now = time.time()

        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                """
                SELECT title, title_is_custom,
                       (SELECT COUNT(*) FROM webui_messages WHERE session_id = ?) AS message_count
                FROM webui_sessions WHERE id = ?
                """,
                (session_id, session_id),
            ).fetchone()
            if row is None:
                raise WebUISessionNotFound("Session not found")

            connection.execute(
                """
                INSERT INTO webui_messages (
                    session_id, role, content_json, sources_json, created_at
                ) VALUES (?, 'user', ?, '[]', ?)
                """,
                (session_id, json.dumps(safe_user_content, ensure_ascii=False), now),
            )
            connection.execute(
                """
                INSERT INTO webui_messages (
                    session_id, role, content_json, sources_json, created_at
                ) VALUES (?, 'assistant', ?, ?, ?)
                """,
                (
                    session_id,
                    json.dumps(assistant_content, ensure_ascii=False),
                    json.dumps(safe_sources, ensure_ascii=False),
                    now,
                ),
            )

            title = row["title"]
            if not bool(row["title_is_custom"]) and int(row["message_count"]) == 0:
                title = _title_from_content(safe_user_content)

            connection.execute(
                """
                UPDATE webui_sessions
                SET title = ?, backend_uuid = ?, attachments_json = ?, model = ?, updated_at = ?
                WHERE id = ?
                """,
                (
                    title,
                    backend_uuid.strip(),
                    json.dumps(attachments, ensure_ascii=False),
                    model,
                    now,
                    session_id,
                ),
            )
        return self.get_session(session_id)

    @contextmanager
    def turn_lock(self, session_id: str) -> Iterator[None]:
        validate_session_id(session_id)
        with self._locks_guard:
            lock = self._turn_locks.setdefault(session_id, threading.Lock())
        lock.acquire()
        try:
            yield
        finally:
            lock.release()


_store: Optional[WebUISessionStore] = None
_store_lock = threading.Lock()


def default_session_database_path() -> Path:
    configured = os.getenv("PPLX_SESSION_DB") or os.getenv("PPLX_WEBUI_SESSION_DB")
    if configured:
        return Path(configured).expanduser()
    return Path.cwd() / "data" / "webui_sessions.sqlite3"


def get_webui_session_store() -> WebUISessionStore:
    global _store
    if _store is None:
        with _store_lock:
            if _store is None:
                _store = WebUISessionStore(default_session_database_path())
    return _store
