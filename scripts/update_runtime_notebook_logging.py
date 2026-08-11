"""Add persistent, redacted runtime logging to the Bob Lightning/Colab notebook."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


LOGGING_BLOCK = r'''

# BOB_STRUCTURED_RUNTIME_LOGGING_V1_BEGIN
# Persistent JSONL observability for Lightning AI/Colab. Raw prompts, generated
# code, workspace contents, credentials, and request headers are never logged.
import hashlib as _bob_hashlib
import threading as _bob_log_threading
import urllib.parse as _bob_urlparse
import uuid as _bob_uuid
from datetime import datetime as _bob_datetime, timezone as _bob_timezone
from pathlib import Path as _BobPath

BOB_RUNTIME_LOG_DIR = _BobPath(os.environ.get("BOB_RUNTIME_LOG_DIR", "bob_runtime_logs")).resolve()
BOB_RUNTIME_LOG_DIR.mkdir(parents=True, exist_ok=True)
_BOB_RUNTIME_LOG_FILES = {
    "app": BOB_RUNTIME_LOG_DIR / "app-events.jsonl",
    "model": BOB_RUNTIME_LOG_DIR / "model-events.jsonl",
    "ngrok": BOB_RUNTIME_LOG_DIR / "ngrok-events.jsonl",
}
_BOB_RUNTIME_LOG_LOCK = globals().get("_BOB_RUNTIME_LOG_LOCK", _bob_log_threading.RLock())
_BOB_RUNTIME_LOG_MAX_BYTES = max(1024 * 1024, int(os.environ.get("BOB_RUNTIME_LOG_MAX_BYTES", str(10 * 1024 * 1024))))
_BOB_LOG_DROPPED_KEYS = {
    "authorization", "cookie", "set-cookie", "password", "password_hash",
    "session", "session_token", "token", "token_hash", "secret", "api_key",
    "code", "content", "files", "generated_code", "output", "request_body",
    "response_body", "headers",
}


def _bob_log_timestamp() -> str:
    return _bob_datetime.now(_bob_timezone.utc).isoformat().replace("+00:00", "Z")


def _bob_configured_secrets():
    values = [
        os.environ.get("BOB_COLAB_TOKEN", ""),
        os.environ.get("HF_TOKEN", ""),
        os.environ.get("NGROK_AUTH_TOKEN", ""),
        os.environ.get("NGROK_AUTHTOKEN", ""),
    ]
    values.extend(os.environ.get("BOB_REDACT_VALUES", "").split(","))
    return [value for value in values if value]


def _bob_redact_log_text(value) -> str:
    text = str(value or "")
    text = re.sub(r"(?i)Bearer\s+[A-Za-z0-9._~+/=-]+", "Bearer [REDACTED]", text)
    text = re.sub(r"(?i)\b(sk-|ghp_|github_pat_|hf_|ngrok_)[A-Za-z0-9_-]{8,}\b", "[REDACTED_TOKEN]", text)
    text = re.sub(r"(?i)(password|passwd|api[_-]?key|secret|token)\s*[:=]\s*[^\s,;]+", r"\1=[REDACTED]", text)
    for secret in _bob_configured_secrets():
        text = text.replace(secret, "[REDACTED_CONFIGURED_SECRET]")
    return text[:100000]


def _bob_sanitize_log_value(value, key=""):
    if str(key).lower() in _BOB_LOG_DROPPED_KEYS:
        return None
    if isinstance(value, str):
        return _bob_redact_log_text(value)
    if isinstance(value, (int, float, bool)) or value is None:
        return value
    if isinstance(value, (list, tuple)):
        return [_bob_sanitize_log_value(item) for item in value]
    if isinstance(value, dict):
        return {
            str(name): safe
            for name, item in value.items()
            if (safe := _bob_sanitize_log_value(item, name)) is not None
        }
    return _bob_redact_log_text(value)


def _bob_prompt_metadata(payload: dict) -> dict:
    prompt = str((payload or {}).get("user_prompt") or (payload or {}).get("prompt") or (payload or {}).get("message") or "")
    encoded = prompt.encode("utf-8")
    return {"prompt_sha256": _bob_hashlib.sha256(encoded).hexdigest(), "prompt_size_bytes": len(encoded)} if prompt else {}


def _bob_runtime_log(source: str, event: str, **payload) -> None:
    file_path = _BOB_RUNTIME_LOG_FILES[source]
    record = _bob_sanitize_log_value({"timestamp": _bob_log_timestamp(), "event": event, **payload})
    line = json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n"
    with _BOB_RUNTIME_LOG_LOCK:
        try:
            if file_path.exists() and file_path.stat().st_size >= _BOB_RUNTIME_LOG_MAX_BYTES:
                backup = file_path.with_suffix(file_path.suffix + ".1")
                if backup.exists():
                    backup.unlink()
                file_path.replace(backup)
            with file_path.open("a", encoding="utf-8") as handle:
                handle.write(line)
                handle.flush()
        except Exception as log_error:
            print("Structured runtime log error:", _bob_redact_log_text(log_error))


print("Structured runtime logs:", BOB_RUNTIME_LOG_DIR)
# BOB_STRUCTURED_RUNTIME_LOGGING_V1_END
'''


def replace_once(source: str, old: str, new: str, label: str) -> str:
    count = source.count(old)
    if count != 1:
        raise RuntimeError(f"Expected one {label} marker, found {count}")
    return source.replace(old, new, 1)


def update_notebook(input_path: Path, output_path: Path) -> None:
    notebook = json.loads(input_path.read_text(encoding="utf-8"))
    cells = notebook.get("cells", [])
    if len(cells) < 34:
        raise RuntimeError("The expected Bob runtime cells are missing")

    def find_code_cell(*markers: str) -> int:
        matches = []
        for index, cell in enumerate(cells):
            if cell.get("cell_type") != "code":
                continue
            source = "".join(cell.get("source", []))
            if all(marker in source for marker in markers):
                matches.append(index)
        if len(matches) != 1:
            raise RuntimeError(f"Expected one notebook cell containing {markers!r}, found {matches}")
        return matches[0]

    runtime_index = find_code_cell('BOB_COLAB_CONTRACT_VERSION = "bob-colab-v4-llmops"', "def create_colab_app", '@app.post("/replan")')
    tunnel_index = find_code_cell("Start and expose the Bob API", "ngrok.connect")
    cleanup_index = find_code_cell("Optional cleanup", "ngrok.kill")

    runtime = "".join(cells[runtime_index].get("source", []))
    if "BOB_STRUCTURED_RUNTIME_LOGGING_V1_BEGIN" not in runtime:
        runtime = replace_once(
            runtime,
            'BOB_COLAB_CONTRACT_VERSION = "bob-colab-v4-llmops"\n',
            'BOB_COLAB_CONTRACT_VERSION = "bob-colab-v4-llmops"\n' + LOGGING_BLOCK,
            "runtime contract",
        )
        runtime = replace_once(
            runtime,
            '    print(json.dumps({"event": "model.stage", **metadata}, ensure_ascii=False))\n',
            '    _bob_runtime_log("model", "model.stage", **metadata)\n    print(json.dumps({"event": "model.stage", **metadata}, ensure_ascii=False))\n',
            "model stage log",
        )
        runtime = replace_once(
            runtime,
            '    print(json.dumps({"event": "model.error", **metadata, "error": error}, ensure_ascii=False))\n',
            '    _bob_runtime_log("model", "model.error", **metadata, error=error)\n    print(json.dumps({"event": "model.error", **metadata, "error": error}, ensure_ascii=False))\n',
            "model error log",
        )
        runtime = replace_once(
            runtime,
            '    from flask import Flask, Response, jsonify, request, stream_with_context\n\n    app = Flask(__name__)\n    app.config["MAX_CONTENT_LENGTH"] = int(os.environ.get("BOB_MAX_REQUEST_BYTES", str(50 * 1024 * 1024)))\n',
            '''    from flask import Flask, Response, g, jsonify, request, stream_with_context

    app = Flask(__name__)
    app.config["MAX_CONTENT_LENGTH"] = int(os.environ.get("BOB_MAX_REQUEST_BYTES", str(50 * 1024 * 1024)))

    @app.before_request
    def structured_request_start():
        g.bob_request_started = time.perf_counter()
        payload = request.get_json(silent=True) or {}
        run_id = payload.get("run_id")
        g.bob_request_id = payload.get("request_id") or request.headers.get("X-Request-ID") or f"req_{_bob_uuid.uuid4().hex}"
        g.bob_trace_id = payload.get("trace_id") or run_id
        g.bob_run_id = run_id
        g.bob_actor_user_id = payload.get("actor_user_id")
        g.bob_prompt_metadata = _bob_prompt_metadata(payload)

    @app.after_request
    def structured_request_finish(response):
        duration_ms = round(max(0.0, time.perf_counter() - getattr(g, "bob_request_started", time.perf_counter())) * 1000)
        metadata = {
            "request_id": getattr(g, "bob_request_id", None),
            "trace_id": getattr(g, "bob_trace_id", None),
            "run_id": getattr(g, "bob_run_id", None),
            "actor_user_id": getattr(g, "bob_actor_user_id", None),
            "method": request.method,
            "path": request.path,
            "status": response.status_code,
            "duration_ms": duration_ms,
            "request_size_bytes": request.content_length or 0,
            "response_size_bytes": response.calculate_content_length(),
            "outcome": "success" if response.status_code < 400 else "error",
            **getattr(g, "bob_prompt_metadata", {}),
        }
        _bob_runtime_log("app", "app.http_request", **metadata)
        forwarded_host = request.headers.get("X-Forwarded-Host", "")
        host = forwarded_host or request.host
        if "ngrok" in host.lower():
            _bob_runtime_log("ngrok", "ngrok.http_request", host=host, forwarded_proto=request.headers.get("X-Forwarded-Proto"), **metadata)
        response.headers["X-Request-ID"] = metadata["request_id"]
        return response
''',
            "Flask request logging",
        )
        runtime = runtime.replace('            "request_tracing": True,\n', '            "request_tracing": True,\n            "structured_logging": True,\n            "runtime_log_dir": str(BOB_RUNTIME_LOG_DIR),\n', 2)
    evaluation_metadata = '''        "evaluation_run_id": payload.get("evaluation_run_id"),
        "test_id": payload.get("test_id"),
        "test_name": payload.get("test_name"),
        "prompt_category": payload.get("prompt_category"),
        "pair_id": payload.get("pair_id"),
        "approach": payload.get("approach"),
'''
    if '"evaluation_run_id": payload.get("evaluation_run_id")' not in runtime:
        runtime = replace_once(
            runtime,
            '        "actor_user_id": payload.get("actor_user_id"),\n        "model": SHARED_MODEL_NAME,\n',
            '        "actor_user_id": payload.get("actor_user_id"),\n' + evaluation_metadata + '        "model": SHARED_MODEL_NAME,\n',
            "evaluation request metadata",
        )
        runtime = replace_once(
            runtime,
            '        g.bob_actor_user_id = payload.get("actor_user_id")\n        g.bob_prompt_metadata = _bob_prompt_metadata(payload)\n',
            '        g.bob_actor_user_id = payload.get("actor_user_id")\n        g.bob_evaluation_metadata = {name: payload.get(name) for name in ("evaluation_run_id", "test_id", "test_name", "prompt_category", "pair_id", "approach")}\n        g.bob_prompt_metadata = _bob_prompt_metadata(payload)\n',
            "evaluation HTTP metadata capture",
        )
        runtime = replace_once(
            runtime,
            '            "outcome": "success" if response.status_code < 400 else "error",\n            **getattr(g, "bob_prompt_metadata", {}),\n',
            '            "outcome": "success" if response.status_code < 400 else "error",\n            **getattr(g, "bob_evaluation_metadata", {}),\n            **getattr(g, "bob_prompt_metadata", {}),\n',
            "evaluation HTTP log metadata",
        )
    cells[runtime_index]["source"] = runtime.splitlines(keepends=True)

    tunnel = "".join(cells[tunnel_index].get("source", []))
    if "ngrok.tunnel_started" not in tunnel:
        tunnel = replace_once(
            tunnel,
            '# 4. Create a fresh public ngrok HTTPS tunnel\n# ---------------------------------------------------------------------------\n\ntry:\n',
            '# 4. Create a fresh public ngrok HTTPS tunnel\n# ---------------------------------------------------------------------------\n\n_bob_ngrok_started = time.perf_counter()\ntry:\n',
            "ngrok start timer",
        )
        tunnel = replace_once(
            tunnel,
            'except Exception as exc:\n    ngrok_log_text = ""\n',
            'except Exception as exc:\n    _bob_runtime_log("ngrok", "ngrok.tunnel_error", duration_ms=round((time.perf_counter() - _bob_ngrok_started) * 1000), error={"type": type(exc).__name__, "message": _safe_error_message(exc)})\n    ngrok_log_text = ""\n',
            "ngrok error log",
        )
        tunnel = replace_once(
            tunnel,
            'if not BASE_URL.startswith("https://"):\n',
            '_bob_runtime_log("ngrok", "ngrok.tunnel_started", duration_ms=round((time.perf_counter() - _bob_ngrok_started) * 1000), public_host=_bob_urlparse.urlsplit(BASE_URL).hostname, port=PORT, tunnel_name=getattr(tunnel, "name", None), tls=BASE_URL.startswith("https://"))\n\nif not BASE_URL.startswith("https://"):\n',
            "ngrok success log",
        )
        tunnel = replace_once(
            tunnel,
            'print("Public Base URL: ", BASE_URL)\n',
            'print("Public Base URL: ", BASE_URL)\nprint("Runtime logs:    ", BOB_RUNTIME_LOG_DIR)\n',
            "runtime log path display",
        )
    cells[tunnel_index]["source"] = tunnel.splitlines(keepends=True)

    cleanup = "".join(cells[cleanup_index].get("source", []))
    if "ngrok.tunnel_stopped" not in cleanup:
        cleanup = replace_once(
            cleanup,
            'try:\n    ngrok.kill()\nexcept Exception as exc:\n',
            'try:\n    ngrok.kill()\n    _bob_runtime_log("ngrok", "ngrok.tunnel_stopped", reason="notebook_cleanup")\nexcept Exception as exc:\n    _bob_runtime_log("ngrok", "ngrok.tunnel_stop_error", error={"type": type(exc).__name__, "message": _safe_error_message(exc)})\n',
            "ngrok cleanup log",
        )
    cells[cleanup_index]["source"] = cleanup.splitlines(keepends=True)

    for cell in cells:
        if cell.get("cell_type") == "code":
            cell["outputs"] = []
            cell["execution_count"] = None
    notebook.setdefault("metadata", {})["bob_runtime_contract"] = "bob-colab-v4-llmops"
    notebook["metadata"]["bob_structured_logging"] = "1.0"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(notebook, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    update_notebook(args.input.resolve(), args.output.resolve())
    print(f"Updated notebook: {args.output.resolve()}")


if __name__ == "__main__":
    main()
