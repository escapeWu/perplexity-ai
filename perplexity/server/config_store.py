"""Atomic configuration persistence. Mount the containing directory, not the file."""
import json
import os
import tempfile
from pathlib import Path


def write_config(path, value, *, only_if_missing=False):
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=".pool-", suffix=".json", dir=target.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        if only_if_missing:
            try:
                os.link(temporary, target)
            except FileExistsError:
                return False
        else:
            os.replace(temporary, target)
        directory = os.open(target.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
        return True
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
