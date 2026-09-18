"""Bounded disk-backed uploads shared by Files API and durable jobs."""
from __future__ import annotations

import json
import os
import re
import threading
import time
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

MAX_FILE_BYTES = 20 * 1024 * 1024
MAX_REQUEST_FILE_BYTES = 100 * 1024 * 1024
MAX_STORED_BYTES = 1024 * 1024 * 1024
FILE_TTL = 86400
_input_owners = 0


@asynccontextmanager
async def attachment_input_budget(enabled=True):
    """Bound resident attachment input through resolution and durable staging."""
    global _input_owners
    if not enabled:
        yield
        return
    if _input_owners >= 2:
        from .job_store import JobError
        raise JobError("Attachment input capacity is full; retry shortly", "queue_full", 429)
    _input_owners += 1
    try:
        yield
    finally:
        _input_owners -= 1



@dataclass
class FileEntry:
    id: str
    filename: str
    data: bytes
    size: int
    created_at: int
    purpose: str


class FilesStore:
    _instance = None
    _lock = threading.Lock()

    def __new__(cls, directory=None):
        if directory is not None:
            return super().__new__(cls)
        with cls._lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
            return cls._instance

    def __init__(self, directory=None):
        if hasattr(self, "directory"):
            return
        from .webui_sessions import default_session_database_path
        self.directory = Path(directory or os.getenv("PPLX_FILES_DIR") or default_session_database_path().parent / "uploads")
        self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        self._rw_lock = threading.RLock()
        self._pins = {}
        self._store = {}
        for path in self.directory.glob("*.json"):
            try:
                meta = json.loads(path.read_text())
                if self._valid_id(meta.get("id")):
                    self._store[meta["id"]] = meta
            except (ValueError, OSError):
                continue

    @staticmethod
    def _valid_id(value):
        return isinstance(value, str) and re.fullmatch(r"[A-Za-z0-9_-]{1,100}", value) is not None

    def _path(self, file_id, suffix=".bin"):
        if not self._valid_id(file_id):
            raise ValueError("Invalid file id")
        return self.directory / (file_id + suffix)

    def put(self, entry: FileEntry):
        if len(entry.data) > MAX_FILE_BYTES:
            raise ValueError("File exceeds 20 MiB limit")
        with self._rw_lock:
            self.prune()
            if len(self._store) >= 1000 or sum(x["size"] for x in self._store.values()) + len(entry.data) > MAX_STORED_BYTES:
                raise ValueError("File storage quota exceeded")
            if entry.id in self._store:
                raise ValueError("File id already exists")
            path = self._path(entry.id)
            with path.open("xb") as f:
                os.chmod(path, 0o600)
                f.write(entry.data)
            meta = {"id": entry.id, "filename": Path(entry.filename).name,
                    "size": len(entry.data), "created_at": entry.created_at, "purpose": entry.purpose}
            metadata = self._path(entry.id, ".json")
            try:
                with metadata.open("x") as f:
                    os.chmod(metadata, 0o600)
                    json.dump(meta, f)
            except BaseException:
                path.unlink(missing_ok=True)
                raise
            self._store[entry.id] = meta

    def stage(self, files: dict[str, bytes]):
        if sum(len(data) for data in files.values()) > MAX_REQUEST_FILE_BYTES:
            raise ValueError("Attachments exceed 100 MiB request limit")
        refs = {}
        try:
            for name, data in files.items():
                file_id = "file-" + uuid4().hex
                self.put(FileEntry(file_id, name, data, len(data), int(time.time()), "assistants"))
                refs[name] = file_id
        except BaseException:
            for file_id in refs.values():
                self.delete(file_id)
            raise
        return refs

    def get(self, file_id):
        if not self._valid_id(file_id):
            return None
        with self._rw_lock:
            meta = self._store.get(file_id)
            if meta is None:
                return None
            if time.time() - meta["created_at"] > FILE_TTL and not self._pins.get(file_id):
                self.delete(file_id)
                return None
            try:
                with self._path(file_id).open("rb") as f:
                    data = f.read(MAX_FILE_BYTES + 1)
            except OSError:
                return None
            if len(data) > MAX_FILE_BYTES:
                raise ValueError("Stored file exceeds size limit")
            return FileEntry(data=data, **meta)

    def load(self, refs):
        files = {}
        for name, file_id in refs.items():
            entry = self.get(file_id)
            if entry is None:
                raise ValueError("Task attachment expired or is missing")
            files[name] = entry.data
        return files

    def pin(self, refs, job_id):
        with self._rw_lock:
            for file_id in refs.values():
                self._pins.setdefault(file_id, set()).add(job_id)

    def unpin(self, refs, job_id):
        with self._rw_lock:
            for file_id in refs.values():
                self._pins.get(file_id, set()).discard(job_id)

    def delete(self, file_id):
        with self._rw_lock:
            if self._pins.get(file_id):
                raise ValueError("File is used by an active task")
            if file_id not in self._store:
                return False
            self._path(file_id).unlink(missing_ok=True)
            self._path(file_id, ".json").unlink(missing_ok=True)
            del self._store[file_id]
            self._pins.pop(file_id, None)
            return True

    def prune(self):
        with self._rw_lock:
            for file_id, meta in list(self._store.items()):
                if time.time() - meta["created_at"] > FILE_TTL and not self._pins.get(file_id):
                    self.delete(file_id)

    @staticmethod
    def to_file_object(entry):
        return {"id": entry.id, "object": "file", "bytes": entry.size,
                "created_at": entry.created_at, "filename": entry.filename, "purpose": entry.purpose}


def get_files_store():
    return FilesStore()
