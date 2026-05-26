import os
import subprocess
import sys
import time
from typing import Dict
from config import WORKSPACE_DIR
from bob_core.file_manager import safe_path

RUNNING_PROCESSES = {}


def _safe_key(project: str, rel_path: str) -> str:
    return f"{project}:{rel_path}"


def run_python(project: str, rel_path: str) -> Dict:
    file_path = safe_path(project, rel_path)
    if not file_path.exists() or file_path.suffix != ".py":
        raise ValueError("Only existing Python files can be run")

    key = _safe_key(project, rel_path)
    old_proc = RUNNING_PROCESSES.get(key)
    if old_proc and old_proc.poll() is None:
        return {
            "command": f"python {rel_path}",
            "returncode": None,
            "stdout": "This file is already running. Stop it first.",
            "stderr": "",
        }

    code = file_path.read_text(encoding="utf-8", errors="replace")
    is_server_like = "app.run(" in code or "Flask(" in code

    env = os.environ.copy()
    env["PYTHONUNBUFFERED"] = "1"

    # Strip ALL Werkzeug reloader env vars so it cannot inherit a socket fd
    # or think it's already inside a reloader child process.
    for key_to_remove in ("WERKZEUG_RUN_MAIN", "WERKZEUG_SERVER_FD",
                          "WERKZEUG_RESTART_PID", "_FLASK_DEBUG_REQ"):
        env.pop(key_to_remove, None)

    # Inject a site-customise shim via PYTHONSTARTUP that monkey-patches
    # Flask's app.run() before the user's code even calls it.
    # This is the only approach that works without modifying the source file
    # and without a temp file that the reloader watches.
    shim = (
        "import flask as _flask\n"
        "_orig_run = _flask.Flask.run\n"
        "def _safe_run(self, *a, **kw):\n"
        "    kw['debug'] = False\n"
        "    kw['use_reloader'] = False\n"
        "    return _orig_run(self, *a, **kw)\n"
        "_flask.Flask.run = _safe_run\n"
    )

    if is_server_like:
        proc = subprocess.Popen(
            [
                sys.executable,
                "-c",
                shim + "\nimport runpy\nrunpy.run_path(r'" + str(file_path).replace("\\", "\\\\") + "', run_name='__main__')",
            ],
            cwd=str(WORKSPACE_DIR / project),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env=env,
        )
        RUNNING_PROCESSES[_safe_key(project, rel_path)] = proc
        time.sleep(1.8)

        if proc.poll() is None:
            return {
                "command": f"python {rel_path}",
                "returncode": None,
                "stdout": (
                    "Server started (reloader disabled automatically).\n"
                    "Open the URL shown by Flask — usually http://127.0.0.1:7000\n"
                    "Click Stop to terminate."
                ),
                "stderr": "",
            }

        stdout, stderr = proc.communicate(timeout=3)
        return {
            "command": f"python {rel_path}",
            "returncode": proc.returncode,
            "stdout": stdout,
            "stderr": stderr,
        }

    else:
        try:
            result = subprocess.run(
                [sys.executable, str(file_path)],
                cwd=str(WORKSPACE_DIR / project),
                capture_output=True,
                text=True,
                timeout=15,
                env=env,
            )
            return {
                "command": f"python {rel_path}",
                "returncode": result.returncode,
                "stdout": result.stdout,
                "stderr": result.stderr,
            }
        except subprocess.TimeoutExpired as exc:
            return {
                "command": f"python {rel_path}",
                "returncode": None,
                "stdout": exc.stdout or "",
                "stderr": "Process timed out after 15 seconds.",
            }


def stop_python(project: str, rel_path: str) -> Dict:
    key = _safe_key(project, rel_path)
    proc = RUNNING_PROCESSES.get(key)
    if not proc or proc.poll() is not None:
        return {"stopped": False, "message": "No running process found for this file."}

    proc.terminate()
    try:
        proc.wait(timeout=3)
    except subprocess.TimeoutExpired:
        proc.kill()
    del RUNNING_PROCESSES[key]
    return {"stopped": True, "message": f"Stopped {rel_path}."}
