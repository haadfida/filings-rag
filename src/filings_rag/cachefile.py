"""Safe on-disk caches: atomic writes, and one lock per cached item.

Answering runs on several threads, and two questions can need the same filing while its cache is cold.
The per-key lock makes the second thread wait for the first instead of reading a half-written file or
computing it twice. PyMuPDF is not thread-safe, so every use of it also holds PDF_LOCK.
Writes go to a temporary file in the same folder and are then renamed into place, so a reader (or a run
interrupted mid-write) never sees a truncated file.
"""

from __future__ import annotations

import os
import tempfile
import threading
from pathlib import Path

PDF_LOCK = threading.RLock()

_locks: dict[str, threading.RLock] = {}
_locks_guard = threading.Lock()


def lock_for(key: str) -> threading.RLock:
    with _locks_guard:
        return _locks.setdefault(key, threading.RLock())


def atomic_write_bytes(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def atomic_write_text(path: Path, text: str) -> None:
    atomic_write_bytes(path, text.encode("utf-8"))
