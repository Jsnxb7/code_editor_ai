"""Small atomic JSON store used by Bob's project metadata."""

from __future__ import annotations

import json
import os
import threading
from pathlib import Path
from typing import Any

_locks: dict[str, threading.RLock] = {}
_locks_guard = threading.Lock()


def project_lock(project: str) -> threading.RLock:
    with _locks_guard:
        return _locks.setdefault(project, threading.RLock())


def load_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def save_json_atomic(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f".{path.name}.{os.getpid()}.{threading.get_ident()}.tmp")
    with temp.open("w", encoding="utf-8", newline="\n") as handle:
        json.dump(data, handle, indent=2, ensure_ascii=False)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temp, path)

