"""Durable task state and atomic native-turn commits on the existing session database."""
from __future__ import annotations

import asyncio
import hashlib
import json
import sqlite3
import time
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

from .webui_sessions import WebUISessionStore, WebUISessionNotFound, SessionBusy

TERMINAL = frozenset({"completed", "failed", "timed_out", "cancelled", "interrupted"})
ACTIVE = frozenset({"queued", "running", "cancelling"})


class JobError(Exception):
    def __init__(self, message, code="job_error", status=400, **details):
        super().__init__(message)
        self.code = self.error_type = code
        self.status = self.status_code = status
        self.details = details


def request_hash(payload, session_id):
    stable = {key: value for key, value in payload.items() if key != "file_ids"}
    return hashlib.sha256(json.dumps({"session_id": session_id, **stable}, sort_keys=True,
                                     ensure_ascii=False).encode()).hexdigest()


def public_job(job, *, snapshot=False):
    result = {key: job[key] for key in (
        "id", "session_id", "account_id", "state", "created_at", "started_at", "finished_at", "updated_at", "seq",
    )}
    result["job_id"] = job["id"]
    result["model"] = job["payload"]["model_id"]
    result["error"] = job["error"]
    result["user_content"] = job["payload"].get("user_content", "")
    if snapshot:
        result["snapshot"] = job["snapshot"]
    return result


class JobStore:
    def __init__(self, sessions: WebUISessionStore):
        self.sessions = sessions
        with sessions._connect() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS chat_jobs (
                    id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL REFERENCES webui_sessions(id) ON DELETE CASCADE,
                    principal TEXT NOT NULL,
                    account_id TEXT,
                    state TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    request_hash TEXT NOT NULL,
                    idempotency_key TEXT,
                    snapshot_json TEXT NOT NULL DEFAULT '{}',
                    error_json TEXT,
                    seq INTEGER NOT NULL DEFAULT 0,
                    event_bytes INTEGER NOT NULL DEFAULT 0,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL,
                    started_at REAL,
                    finished_at REAL
                );
                CREATE UNIQUE INDEX IF NOT EXISTS idx_active_session_job
                    ON chat_jobs(session_id) WHERE state IN ('queued','running','cancelling');
                CREATE UNIQUE INDEX IF NOT EXISTS idx_job_idempotency
                    ON chat_jobs(principal,idempotency_key) WHERE idempotency_key IS NOT NULL;
                CREATE INDEX IF NOT EXISTS idx_jobs_updated ON chat_jobs(updated_at DESC);
                CREATE TABLE IF NOT EXISTS chat_job_events (
                    job_id TEXT NOT NULL REFERENCES chat_jobs(id) ON DELETE CASCADE,
                    seq INTEGER NOT NULL,
                    type TEXT NOT NULL,
                    data_json TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    PRIMARY KEY(job_id,seq)
                );
            """)

    @staticmethod
    def _decode(row):
        job = dict(row)
        for key in ("payload", "snapshot", "error"):
            job[key] = json.loads(job.pop(key + "_json") or "null")
        return job

    def get(self, job_id, principal="default"):
        with self.sessions._connect() as conn:
            row = conn.execute("SELECT * FROM chat_jobs WHERE id=? AND principal=?", (job_id, principal)).fetchone()
        if row is None:
            raise JobError("Task not found", "job_not_found", 404)
        return self._decode(row)

    def list(self, *, session_id=None, active=False, limit=50, before=None, principal="default", include_snapshot=False):
        clauses, values = ["principal=?"], [principal]
        if session_id:
            clauses.append("session_id=?"); values.append(session_id)
        if active:
            clauses.append("state IN ('queued','running','cancelling')")
        if before:
            cursor = str(before)
            if "|" in cursor:
                stamp, row_id = cursor.split("|", 1)
                clauses.append("(created_at<? OR (created_at=? AND id<?))")
                values.extend([float(stamp), float(stamp), row_id])
            else:
                clauses.append("created_at<?"); values.append(float(before))
        values.append(min(201, max(1, limit)))
        # Lists need metadata, not hundreds of complete answer snapshots.
        columns = "*" if include_snapshot else "id,session_id,principal,account_id,state,payload_json,request_hash,idempotency_key,'{}' AS snapshot_json,error_json,seq,event_bytes,created_at,updated_at,started_at,finished_at"
        with self.sessions._connect() as conn:
            rows = conn.execute("SELECT " + columns + " FROM chat_jobs WHERE " + " AND ".join(clauses) + " ORDER BY created_at DESC,id DESC LIMIT ?", values).fetchall()
        return [self._decode(row) for row in rows]

    def find_request(self, session_id, payload, key, principal="default"):
        if key is None:
            return None
        if not isinstance(key, str) or not key.strip() or len(key) > 200:
            raise JobError("Idempotency-Key must be 1..200 characters", "invalid_request_error")
        with self.sessions._connect() as conn:
            row = conn.execute("SELECT * FROM chat_jobs WHERE principal=? AND idempotency_key=?", (principal, key)).fetchone()
        if row is None:
            return None
        if row["request_hash"] != request_hash(payload, session_id):
            raise JobError("Idempotency key was used with different input", "idempotency_conflict", 409)
        return self._decode(row)

    def create(self, session_id, payload, *, origin="webui", key=None, principal="default", account_id=None):
        if key is not None and (not isinstance(key, str) or not key.strip() or len(key) > 200):
            raise JobError("Idempotency-Key must be 1..200 characters", "invalid_request_error")
        digest = request_hash(payload, session_id)
        now, job_id = time.time(), "job_" + uuid4().hex
        with self.sessions._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            if key:
                existing = conn.execute("SELECT * FROM chat_jobs WHERE principal=? AND idempotency_key=?", (principal, key)).fetchone()
                if existing:
                    if existing["request_hash"] != digest:
                        raise JobError("Idempotency key was used with different input", "idempotency_conflict", 409)
                    return self._decode(existing), False
            if session_id is None:
                session_id = self.sessions.create_session(origin=origin, _connection=conn).id
            session = conn.execute("SELECT * FROM webui_sessions WHERE id=?", (session_id,)).fetchone()
            if not session:
                raise WebUISessionNotFound("Session not found")
            active = conn.execute("SELECT id FROM chat_jobs WHERE session_id=? AND state IN ('queued','running','cancelling')", (session_id,)).fetchone()
            if active:
                raise JobError("This session already has an active task", "session_busy", 409, active_job_id=active["id"])
            account_id = session["client_id"] or account_id
            if not account_id:
                raise JobError("A task requires an account binding", "account_unavailable", 503)
            conn.execute("UPDATE webui_sessions SET client_id=? WHERE id=? AND client_id IS NULL", (account_id, session_id))
            conn.execute("""INSERT INTO chat_jobs(id,session_id,principal,account_id,state,payload_json,
                request_hash,idempotency_key,created_at,updated_at) VALUES(?,?,?,?,'queued',?,?,?,?,?)""",
                (job_id, session_id, principal, account_id, json.dumps(payload, ensure_ascii=False), digest, key, now, now))
        return self.get(job_id, principal), True

    def bind(self, job_id, account_id):
        with self.sessions._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute("SELECT session_id,state FROM chat_jobs WHERE id=?", (job_id,)).fetchone()
            if not row or row["state"] != "queued":
                return
            conn.execute("UPDATE webui_sessions SET client_id=? WHERE id=? AND client_id IS NULL", (account_id, row["session_id"]))
            bound = conn.execute("SELECT client_id FROM webui_sessions WHERE id=?", (row["session_id"],)).fetchone()[0]
            conn.execute("UPDATE chat_jobs SET account_id=? WHERE id=?", (bound, job_id))

    def start(self, job_id):
        now = time.time()
        with self.sessions._connect() as conn:
            result = conn.execute("UPDATE chat_jobs SET state='running',started_at=?,updated_at=? WHERE id=? AND state='queued'", (now, now, job_id))
        return bool(result.rowcount)

    @staticmethod
    def _event(conn, job_id, kind, data):
        encoded = json.dumps(data, ensure_ascii=False)
        row = conn.execute("SELECT seq,event_bytes FROM chat_jobs WHERE id=?", (job_id,)).fetchone()
        size = len(encoded.encode())
        if row["event_bytes"] + size > 8 * 1024 * 1024 and kind != "terminal":
            raise JobError("Task event budget exceeded", "event_limit", 502)
        seq = row["seq"] + 1
        conn.execute("INSERT INTO chat_job_events VALUES(?,?,?,?,?)", (job_id, seq, kind, encoded, time.time()))
        conn.execute("UPDATE chat_jobs SET seq=?,event_bytes=event_bytes+?,updated_at=? WHERE id=?", (seq, size, time.time(), job_id))
        return seq

    def publish(self, job_id, kind, data, snapshot):
        with self.sessions._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute("SELECT state FROM chat_jobs WHERE id=?", (job_id,)).fetchone()
            if not row or row["state"] != "running":
                return None
            seq = self._event(conn, job_id, kind, data)
            conn.execute("UPDATE chat_jobs SET snapshot_json=? WHERE id=?", (json.dumps(snapshot, ensure_ascii=False), job_id))
        return seq

    def complete(self, job_id, result, follow_up):
        with self.sessions._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute("SELECT * FROM chat_jobs WHERE id=?", (job_id,)).fetchone()
            if not row or row["state"] != "running":
                return False
            job = self._decode(row)
            session = self.sessions.commit_turn(job["session_id"],
                user_content=job["payload"]["user_content"], assistant_content=result.get("answer", ""),
                sources=result.get("sources", []), backend_uuid=follow_up.get("backend_uuid"),
                attachments=follow_up.get("attachments", []), model=job["payload"]["model_id"],
                job_id=job_id, _connection=conn)
            result = {**result, "session": session.to_public_dict(), "job_id": job_id}
            conn.execute("UPDATE chat_jobs SET state='completed',snapshot_json=?,finished_at=? WHERE id=?", (json.dumps(result, ensure_ascii=False), time.time(), job_id))
            self._event(conn, job_id, "terminal", {"state": "completed"})
        return True

    def finish(self, job_id, state, error=None):
        if state not in TERMINAL - {"completed"}:
            raise ValueError("Invalid terminal state")
        with self.sessions._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute("SELECT state,snapshot_json FROM chat_jobs WHERE id=?", (job_id,)).fetchone()
            if not row or row["state"] in TERMINAL:
                return False
            if row["state"] == "cancelling":
                state, error = "cancelled", None
            snapshot = json.loads(row["snapshot_json"])
            for progress in snapshot.get("progress", []):
                if progress.get("status") == "running":
                    progress["status"] = "cancelled" if state == "cancelled" else "failed"
            conn.execute("UPDATE chat_jobs SET state=?,error_json=?,snapshot_json=?,finished_at=? WHERE id=?", (state, json.dumps(error), json.dumps(snapshot, ensure_ascii=False), time.time(), job_id))
            self._event(conn, job_id, "terminal", {"state": state, "error": error})
        return True

    def cancel(self, job_id, principal="default"):
        with self.sessions._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute("SELECT state FROM chat_jobs WHERE id=? AND principal=?", (job_id, principal)).fetchone()
            if row is None:
                raise JobError("Task not found", "job_not_found", 404)
            state = row["state"]
            if state == "queued":
                conn.execute("UPDATE chat_jobs SET state='cancelled',finished_at=? WHERE id=?", (time.time(), job_id))
                self._event(conn, job_id, "terminal", {"state": "cancelled"})
            elif state == "running":
                conn.execute("UPDATE chat_jobs SET state='cancelling' WHERE id=?", (job_id,))
                self._event(conn, job_id, "state", {"state": "cancelling"})
        return self.get(job_id, principal)

    def events(self, job_id, after, limit=100):
        with self.sessions._connect() as conn:
            rows = conn.execute("SELECT * FROM chat_job_events WHERE job_id=? AND seq>? ORDER BY seq LIMIT ?", (job_id, after, min(limit, 200))).fetchall()
        return [{"seq": row["seq"], "type": row["type"], "data": json.loads(row["data_json"])} for row in rows]

    def ping(self):
        with self.sessions._connect() as conn:
            schema_ok = conn.execute("SELECT COUNT(*) FROM sqlite_master WHERE name IN ('webui_sessions','chat_jobs','chat_job_events')").fetchone()[0] == 3
            if schema_ok:
                conn.execute("UPDATE chat_jobs SET updated_at=updated_at WHERE 0")
            return schema_ok

    def recover(self):
        with self.sessions._connect() as conn:
            rows = conn.execute("SELECT id,state FROM chat_jobs WHERE state IN ('queued','running','cancelling') ORDER BY created_at,id LIMIT 2049").fetchall()
        if len(rows) > 2048:
            raise RuntimeError("Task recovery exceeds the configured maximum admission budget")
        queued = []
        for row in rows:
            if row["state"] != "queued":
                self.finish(row["id"], "interrupted", {"code": "process_interrupted", "message": "Service restarted during execution"})
            else:
                queued.append(self.get(row["id"]))
        self.prune_events()
        return queued

    def prune_events(self):
        with self.sessions._connect() as conn:
            conn.execute("DELETE FROM chat_job_events WHERE job_id IN (SELECT id FROM chat_jobs WHERE finished_at<?)", (time.time() - 86400,))


class AsyncJobStore:
    """SQLite runs on a dedicated, bounded executor, never on the ASGI event loop."""
    def __init__(self, store: JobStore):
        self.store = store
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="chat-store")
        self.readers = ThreadPoolExecutor(max_workers=2, thread_name_prefix="chat-read")
        self.read_methods = {store.get, store.list, store.events, store.find_request,
                             store.sessions.get_session, store.sessions.get_messages,
                             store.sessions.list_sessions, store.sessions.has_messages_before}
        self.capacity = asyncio.Semaphore(128)
        self.pending = set()
        self.closed = False

    async def call(self, method, *args, **kwargs):
        if self.closed:
            raise JobError("Task store is closing", "service_unavailable", 503)
        await self.capacity.acquire()
        if self.closed:
            self.capacity.release()
            raise JobError("Task store is closing", "service_unavailable", 503)
        loop = asyncio.get_running_loop()
        try:
            executor = self.readers if method in self.read_methods else self.executor
            future = loop.run_in_executor(executor, lambda: method(*args, **kwargs))
        except BaseException:
            self.capacity.release()
            raise
        self.pending.add(future)
        def finished(f):
            self.pending.discard(f)
            self.capacity.release()
            if not f.cancelled():
                f.exception()  # Observe work whose original waiter was cancelled.
        future.add_done_callback(finished)
        return await asyncio.shield(future)

    async def close(self):
        self.closed = True
        if self.pending:
            await asyncio.gather(*list(self.pending), return_exceptions=True)
        self.executor.shutdown(wait=False)
        self.readers.shutdown(wait=False)
