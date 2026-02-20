"""
In-memory file store for the OpenAI-compatible Files API.

Files are stored for the lifetime of the process only.
Thread-safe via threading.Lock.
"""

import time
import threading
from dataclasses import dataclass


@dataclass
class FileEntry:
    id: str
    filename: str
    data: bytes
    size: int
    created_at: int
    purpose: str


class FilesStore:
    """Thread-safe singleton in-memory store for uploaded files."""

    _instance: "FilesStore | None" = None
    _lock: threading.Lock = threading.Lock()

    def __new__(cls) -> "FilesStore":
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    inst = super().__new__(cls)
                    inst._store: dict[str, FileEntry] = {}
                    inst._rw_lock = threading.Lock()
                    cls._instance = inst
        return cls._instance

    def put(self, entry: FileEntry) -> None:
        with self._rw_lock:
            self._store[entry.id] = entry

    def get(self, file_id: str) -> FileEntry | None:
        with self._rw_lock:
            return self._store.get(file_id)

    def delete(self, file_id: str) -> bool:
        """Returns True if the entry existed and was removed."""
        with self._rw_lock:
            if file_id in self._store:
                del self._store[file_id]
                return True
            return False

    def to_file_object(self, entry: FileEntry) -> dict:
        return {
            "id": entry.id,
            "object": "file",
            "bytes": entry.size,
            "created_at": entry.created_at,
            "filename": entry.filename,
            "purpose": entry.purpose,
        }


def get_files_store() -> FilesStore:
    return FilesStore()
