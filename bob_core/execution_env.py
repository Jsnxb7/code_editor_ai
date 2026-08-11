"""Build a minimal, per-user environment for workspace child processes."""

from __future__ import annotations

import os
import re
from pathlib import Path

from bob_core.file_manager import safe_path


_INHERITED_NAMES = ("PATH", "PATHEXT", "SystemRoot", "COMSPEC", "WINDIR", "LANG", "LC_ALL", "SHELL")


def _safe_user_segment(actor_user_id: str | None) -> str:
    value = re.sub(r"[^A-Za-z0-9_.-]+", "_", str(actor_user_id or "anonymous")).strip("._")
    return value[:80] or "anonymous"


def workspace_process_env(project: str, actor_user_id: str | None = None) -> dict[str, str]:
    """Exclude server secrets and give each user private process state."""
    root = safe_path(project)
    user_id = _safe_user_segment(actor_user_id)
    runtime_root: Path = root / ".bob" / "runtime" / user_id
    runtime_root.mkdir(parents=True, exist_ok=True)
    env = {name: os.environ[name] for name in _INHERITED_NAMES if os.environ.get(name)}
    env.update({
        "HOME": str(runtime_root),
        "USERPROFILE": str(runtime_root),
        "TEMP": str(runtime_root),
        "TMP": str(runtime_root),
        "BOB_USER_ID": user_id,
        "BOB_WORKSPACE": str(root),
    })
    return env
