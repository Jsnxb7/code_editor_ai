"""Runtime model/Colab connection configuration for Bob IDE.

The IDE can still be configured through environment variables, but the Bob chat
panel can now save a local runtime config so demonstrations do not require users
to restart the Python MCP service every time the Colab/ngrok URL changes.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from bob_core.json_store import load_json, save_json_atomic
from config import DATA_DIR

CONFIG_PATH = DATA_DIR / "model_config.json"

DEFAULT_MODEL_CONFIG: dict[str, Any] = {
    "base_url": "",
    "plan_path": "/plan",
    "run_path": "/run-agent",
    "timeout": 600,
    "token": "",
    "headers_json": "{}",
    "updated_at": None,
}


def _clean_path(value: str | None, fallback: str) -> str:
    path = (value or fallback).strip() or fallback
    return path if path.startswith("/") else f"/{path}"


def _clean_timeout(value: Any) -> int:
    try:
        timeout = int(value)
    except (TypeError, ValueError):
        timeout = 600
    return max(5, min(timeout, 3600))


def _validate_headers_json(value: str | dict | None) -> str:
    if value is None or value == "":
        return "{}"
    if isinstance(value, dict):
        return json.dumps(value, ensure_ascii=False)
    try:
        parsed = json.loads(str(value))
    except json.JSONDecodeError as exc:
        raise ValueError("Headers must be valid JSON") from exc
    if not isinstance(parsed, dict):
        raise ValueError("Headers JSON must be an object")
    return json.dumps(parsed, ensure_ascii=False)


def _env_config() -> dict[str, Any]:
    env: dict[str, Any] = {}
    if os.getenv("BOB_COLAB_BASE_URL") is not None:
        env["base_url"] = os.getenv("BOB_COLAB_BASE_URL", "").rstrip("/")
    if os.getenv("BOB_COLAB_PLAN_PATH") is not None:
        env["plan_path"] = _clean_path(os.getenv("BOB_COLAB_PLAN_PATH"), "/plan")
    if os.getenv("BOB_COLAB_RUN_PATH") is not None:
        env["run_path"] = _clean_path(os.getenv("BOB_COLAB_RUN_PATH"), "/run-agent")
    if os.getenv("BOB_COLAB_TIMEOUT") is not None:
        env["timeout"] = _clean_timeout(os.getenv("BOB_COLAB_TIMEOUT"))
    if os.getenv("BOB_COLAB_TOKEN") is not None:
        env["token"] = os.getenv("BOB_COLAB_TOKEN", "")
    if os.getenv("BOB_COLAB_HEADERS_JSON") is not None:
        env["headers_json"] = os.getenv("BOB_COLAB_HEADERS_JSON", "{}")
    return env


def read_model_config(include_secret: bool = False) -> dict[str, Any]:
    """Return effective model config.

    Environment variables take precedence over saved values when set. This keeps
    existing terminal-based workflows working, while allowing UI configuration in
    normal demos.
    """
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    saved = load_json(CONFIG_PATH, DEFAULT_MODEL_CONFIG.copy())
    merged = {**DEFAULT_MODEL_CONFIG, **saved}
    env = _env_config()
    for key, value in env.items():
        merged[key] = value
    merged["base_url"] = str(merged.get("base_url") or "").rstrip("/")
    merged["plan_path"] = _clean_path(merged.get("plan_path"), "/plan")
    merged["run_path"] = _clean_path(merged.get("run_path"), "/run-agent")
    merged["timeout"] = _clean_timeout(merged.get("timeout"))
    merged["headers_json"] = _validate_headers_json(merged.get("headers_json"))
    merged["configured"] = bool(merged["base_url"])
    merged["token_set"] = bool(merged.get("token"))
    if not include_secret:
        merged.pop("token", None)
    return merged


def save_model_config(
    base_url: str | None = None,
    plan_path: str | None = None,
    run_path: str | None = None,
    timeout: int | str | None = None,
    token: str | None = None,
    headers_json: str | dict | None = None,
) -> dict[str, Any]:
    from datetime import datetime, timezone

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    current = load_json(CONFIG_PATH, DEFAULT_MODEL_CONFIG.copy())
    if base_url is not None:
        current["base_url"] = str(base_url).strip().rstrip("/")
    if plan_path is not None:
        current["plan_path"] = _clean_path(plan_path, "/plan")
    if run_path is not None:
        current["run_path"] = _clean_path(run_path, "/run-agent")
    if timeout is not None:
        current["timeout"] = _clean_timeout(timeout)
    if token is not None:
        current["token"] = str(token)
    if headers_json is not None:
        current["headers_json"] = _validate_headers_json(headers_json)
    current["updated_at"] = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    save_json_atomic(CONFIG_PATH, current)
    return read_model_config(include_secret=False)
