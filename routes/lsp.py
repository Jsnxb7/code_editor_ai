"""
LSP proxy — bridges the browser (JSON-RPC over Socket.IO) with a
per-project Pyright stdio language server.

Architecture
------------
Browser  ←── Socket.IO (lsp:* events) ──►  Flask-SocketIO
                                                │
                                         lsp_manager (one Pyright
                                          process per project)
                                                │
                                         Pyright via stdio
                                         (LSP JSON-RPC framing)

Each Socket.IO client joins a room named after its project so that
server → client messages are routed to the right browser tab.
"""

from __future__ import annotations

import json
import logging
import subprocess
import sys
import threading
from pathlib import Path
from typing import Dict

from flask_socketio import SocketIO, emit, join_room

from config import WORKSPACE_DIR

log = logging.getLogger(__name__)

# ── Pyright process pool ────────────────────────────────────────────────────


class PyrightProcess:
    """Manages one Pyright stdio process for a single workspace folder."""

    def __init__(self, project: str, socketio: SocketIO):
        self.project = project
        self.root = str((WORKSPACE_DIR / project).resolve())
        self.socketio = socketio
        self._proc: subprocess.Popen | None = None
        self._lock = threading.Lock()
        self._reader: threading.Thread | None = None

    # ---- public ----

    def send(self, payload: dict) -> None:
        """Send a JSON-RPC message to Pyright."""
        proc = self._ensure_running()
        if proc is None:
            return
        body = json.dumps(payload)
        header = f"Content-Length: {len(body)}\r\n\r\n"
        with self._lock:
            try:
                proc.stdin.write((header + body).encode())
                proc.stdin.flush()
            except OSError as exc:
                log.warning("LSP send error (%s): %s", self.project, exc)

    def stop(self) -> None:
        if self._proc and self._proc.poll() is None:
            self._proc.terminate()

    # ---- private ----

    def _ensure_running(self) -> subprocess.Popen | None:
        if self._proc and self._proc.poll() is None:
            return self._proc
        self._proc = self._start()
        return self._proc

    def _start(self) -> subprocess.Popen | None:
        pyright_cmd = self._find_pyright()
        if not pyright_cmd:
            log.warning("Pyright not found — LSP disabled for %s", self.project)
            return None
        try:
            proc = subprocess.Popen(
                pyright_cmd + ["--stdio"],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                cwd=self.root,
            )
            self._reader = threading.Thread(
                target=self._read_loop, args=(proc,), daemon=True
            )
            self._reader.start()
            log.info("Pyright started for project '%s' (pid %s)", self.project, proc.pid)
            return proc
        except Exception as exc:
            log.error("Failed to start Pyright: %s", exc)
            return None

    @staticmethod
    def _find_pyright() -> list[str] | None:
        """Look for pyright-langserver on PATH (npm or pip install)."""
        import shutil

        for candidate in ("pyright-langserver", "pyright"):
            path = shutil.which(candidate)
            if path:
                return [path]
        # Try next to the current Python interpreter (pip install pyright)
        py_bin = Path(sys.executable).parent
        for candidate in ("pyright-langserver", "pyright"):
            p = py_bin / candidate
            if p.exists():
                return [str(p)]
        return None

    def _read_loop(self, proc: subprocess.Popen) -> None:
        """Read LSP messages from Pyright stdout and forward to the browser."""
        buf = b""
        while True:
            try:
                chunk = proc.stdout.read(4096)
            except Exception:
                break
            if not chunk:
                break
            buf += chunk
            while True:
                header_end = buf.find(b"\r\n\r\n")
                if header_end == -1:
                    break
                header = buf[:header_end].decode(errors="replace")
                length = 0
                for line in header.split("\r\n"):
                    if line.lower().startswith("content-length:"):
                        length = int(line.split(":")[1].strip())
                body_start = header_end + 4
                if len(buf) < body_start + length:
                    break
                body = buf[body_start : body_start + length]
                buf = buf[body_start + length :]
                try:
                    msg = json.loads(body)
                    self.socketio.emit(
                        "lsp:message",
                        msg,
                        room=self.project,
                        namespace="/lsp",
                    )
                except Exception as exc:
                    log.debug("LSP parse error: %s", exc)
        log.info("Pyright exited for project '%s'", self.project)


# ── Process registry ────────────────────────────────────────────────────────

_processes: Dict[str, PyrightProcess] = {}
_registry_lock = threading.Lock()


def _get_or_create(project: str, socketio: SocketIO) -> PyrightProcess:
    with _registry_lock:
        if project not in _processes:
            _processes[project] = PyrightProcess(project, socketio)
        return _processes[project]


# ── Socket.IO event registration ────────────────────────────────────────────


def register_lsp_events(socketio: SocketIO) -> None:
    """Call this from realtime.py after SocketIO is created."""

    @socketio.on("lsp:join", namespace="/lsp")
    def on_join(data):
        project = data.get("project", "")
        if not project:
            return
        join_room(project)
        _get_or_create(project, socketio)
        emit("lsp:ready", {"project": project}, namespace="/lsp")

    @socketio.on("lsp:message", namespace="/lsp")
    def on_message(data):
        project = data.get("project", "")
        payload = data.get("message", {})
        if not project or not payload:
            return
        proc = _get_or_create(project, socketio)
        proc.send(payload)
