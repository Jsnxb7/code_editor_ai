"""Redacted rotating JSONL logs for model lifecycle and tunnel transport."""

from __future__ import annotations

import hashlib
import json
import os
import re
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from config import DATA_DIR

RUNTIME_LOG_DIR = DATA_DIR / "runtime"
MODEL_LOG_PATH = RUNTIME_LOG_DIR / "model-events.jsonl"
TUNNEL_LOG_PATH = RUNTIME_LOG_DIR / "ngrok-events.jsonl"
MAX_LOG_BYTES = 10 * 1024 * 1024
_LOCK = threading.RLock()
_DROP_KEYS = {
    "authorization", "cookie", "set-cookie", "session_token", "password",
    "password_hash", "token", "token_hash", "secret", "code", "content",
    "files", "forced_files", "output",
}
_SECRET_PATTERNS = (
    re.compile(r"(?i)(bearer\s+)[A-Za-z0-9._~+/=-]+"),
    re.compile(r"(?i)\b(sk-|ghp_|github_pat_|hf_|ngrok_)[A-Za-z0-9_-]{8,}\b"),
    re.compile(r"(?i)((?:password|passwd|api[_-]?key|secret|token)\s*[:=]\s*)[^\s,;]+"),
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _redact_text(value: str) -> str:
    result = value
    for pattern in _SECRET_PATTERNS:
        result = pattern.sub(r"\1[REDACTED]", result)
    configured = [os.getenv("BOB_COLAB_TOKEN", ""), *os.getenv("BOB_REDACT_VALUES", "").split(",")]
    for secret in filter(None, configured):
        result = result.replace(secret, "[REDACTED_CONFIGURED_SECRET]")
    return result[:100_000]


def sanitize(value: Any, key: str = "") -> Any:
    if key.lower() in _DROP_KEYS:
        return None
    if isinstance(value, str):
        return _redact_text(value)
    if isinstance(value, list):
        return [sanitized for item in value if (sanitized := sanitize(item)) is not None]
    if isinstance(value, dict):
        return {
            name: sanitized
            for name, item in value.items()
            if (sanitized := sanitize(item, str(name))) is not None
        }
    return value


def prompt_metadata(prompt: str | None) -> dict[str, Any]:
    encoded = str(prompt or "").encode("utf-8")
    return {"prompt_sha256": hashlib.sha256(encoded).hexdigest(), "prompt_size_bytes": len(encoded)}


def _rotate(path: Path) -> None:
    try:
        if path.stat().st_size <= MAX_LOG_BYTES:
            return
    except FileNotFoundError:
        return
    prior = path.with_suffix(path.suffix + ".1")
    prior.unlink(missing_ok=True)
    path.replace(prior)


def append_jsonl(path: Path, event: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    record = sanitize({"timestamp": _now(), "event": event, **(payload or {})})
    path.parent.mkdir(parents=True, exist_ok=True)
    with _LOCK:
        _rotate(path)
        with path.open("a", encoding="utf-8", newline="\n") as stream:
            stream.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n")
            stream.flush()
    return record


def log_model(event: str, **payload: Any) -> dict[str, Any]:
    return append_jsonl(MODEL_LOG_PATH, event, payload)


def log_tunnel(event: str, **payload: Any) -> dict[str, Any]:
    return append_jsonl(TUNNEL_LOG_PATH, event, payload)

