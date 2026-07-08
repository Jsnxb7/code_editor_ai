import os
import re
import subprocess
import sys
from typing import Dict

from bob_core.file_manager import safe_path

RUNNING_PROCESSES = {}


def _safe_key(project: str, rel_path: str) -> str:
    return f"{project}:{rel_path}"


def run_python(project: str, rel_path: str, timeout: int = 15) -> Dict:
    """
    Headless one-shot run of a Python file, capturing stdout/stderr.

    This is a utility for tooling (search_workspace's sibling helpers, a
    future Bob Assistant action, etc.) — not for the IDE's Run button, which
    now types `python <file>` straight into a real terminal tab so servers,
    REPLs, and interactive scripts behave exactly like they would in a normal
    shell.
    """
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

    env = os.environ.copy()
    env["PYTHONUNBUFFERED"] = "1"

    try:
        result = subprocess.run(
            [sys.executable, str(file_path)],
            cwd=str(safe_path(project)),
            capture_output=True,
            text=True,
            timeout=timeout,
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
            "stderr": f"Process timed out after {timeout} seconds.",
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


def run_pytest(project: str) -> Dict:
    root = safe_path(project)
    try:
        result = subprocess.run(
            [sys.executable, "-m", "pytest"],
            cwd=str(root),
            capture_output=True,
            text=True,
            timeout=30,
        )
    except FileNotFoundError:
        return {
            "command": "pytest",
            "returncode": 1,
            "stdout": "",
            "stderr": "pytest is not installed in this Python environment.",
            "passed": 0,
            "failed": 0,
        }
    except subprocess.TimeoutExpired as exc:
        return {
            "command": "pytest",
            "returncode": None,
            "stdout": exc.stdout or "",
            "stderr": "pytest timed out after 30 seconds.",
            "passed": 0,
            "failed": 0,
        }

    output = f"{result.stdout}\n{result.stderr}"
    return {
        "command": "pytest",
        "returncode": result.returncode,
        "stdout": result.stdout,
        "stderr": result.stderr,
        "passed": _count_pytest_status(output, "passed"),
        "failed": _count_pytest_status(output, "failed"),
    }


def _count_pytest_status(output: str, status: str) -> int:
    match = re.search(rf"(\d+)\s+{re.escape(status)}", output)
    if match:
        return int(match.group(1))
    return 0
