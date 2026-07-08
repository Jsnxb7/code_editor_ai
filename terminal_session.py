"""
Real PTY-backed terminal sessions.

Each browser tab can open one or more terminal tabs (like VS Code). Each one
maps to an actual pseudo-terminal running a real login shell, so everything
that works in a normal terminal — readline history, arrow keys, Ctrl+C,
tab-completion, interactive REPLs, `vim`, long-running dev servers, etc. —
works here too. We are not parsing "commands"; we are streaming raw bytes
between the browser and a real shell process.

On POSIX (Linux/macOS) this uses the standard library `pty` module, which is
how every terminal emulator (including the one inside VS Code) talks to a
shell. On Windows, a true PTY needs ConPTY; we use `pywinpty` if it is
installed, and fall back to a best-effort pipe-based shell otherwise.
"""

from __future__ import annotations

import os
import platform
import signal
import struct
import threading
from pathlib import Path
from typing import Callable, Dict, Optional

IS_WINDOWS = platform.system() == "Windows"

if not IS_WINDOWS:
    import fcntl
    import pty
    import select
    import termios


class TerminalSession:
    """One real shell process wired to one terminal tab in the browser."""

    def __init__(self, terminal_id: str, cwd: Path, on_data: Callable[[str], None],
                 on_exit: Callable[[], None]):
        self.terminal_id = terminal_id
        self.cwd = cwd
        self.on_data = on_data
        self.on_exit = on_exit
        self.alive = False
        self._lock = threading.Lock()

    # -- to be implemented by subclasses --
    def start(self):
        raise NotImplementedError

    def write(self, data: str):
        raise NotImplementedError

    def resize(self, cols: int, rows: int):
        raise NotImplementedError

    def stop(self):
        raise NotImplementedError


class PosixPtySession(TerminalSession):
    """Real PTY session for Linux/macOS using the stdlib `pty` module."""

    def start(self):
        shell = os.environ.get("SHELL") or "/bin/bash"
        if not Path(shell).exists():
            shell = "/bin/sh"

        pid, fd = pty.fork()
        if pid == 0:
            # Child process: replace ourselves with a real interactive shell.
            try:
                os.chdir(str(self.cwd))
            except OSError:
                pass
            env = os.environ.copy()
            env["TERM"] = "xterm-256color"
            env["BOB_IDE"] = "1"
            try:
                os.execvpe(shell, [shell, "-i"], env)
            except OSError:
                os._exit(1)
        else:
            self.pid = pid
            self.fd = fd
            self.alive = True
            self._set_winsize(24, 80)
            self._reader = threading.Thread(target=self._read_loop, daemon=True)
            self._reader.start()

    def _read_loop(self):
        while self.alive:
            try:
                ready, _, _ = select.select([self.fd], [], [], 0.5)
            except (OSError, ValueError):
                break
            if not ready:
                continue
            try:
                data = os.read(self.fd, 65536)
            except OSError:
                break
            if not data:
                break
            self.on_data(data.decode("utf-8", errors="replace"))
        self.alive = False
        self.on_exit()

    def write(self, data: str):
        if not self.alive:
            return
        try:
            os.write(self.fd, data.encode("utf-8", errors="ignore"))
        except OSError:
            pass

    def resize(self, cols: int, rows: int):
        self._set_winsize(rows, cols)

    def _set_winsize(self, rows: int, cols: int):
        if not getattr(self, "fd", None):
            return
        try:
            winsize = struct.pack("HHHH", rows, cols, 0, 0)
            fcntl.ioctl(self.fd, termios.TIOCSWINSZ, winsize)
        except OSError:
            pass

    def stop(self):
        self.alive = False
        pid = getattr(self, "pid", None)
        if pid:
            try:
                os.kill(pid, signal.SIGHUP)
            except ProcessLookupError:
                pass
        fd = getattr(self, "fd", None)
        if fd is not None:
            try:
                os.close(fd)
            except OSError:
                pass


class WindowsWinptySession(TerminalSession):
    """Real ConPTY session for Windows, via the optional `pywinpty` package."""

    def start(self):
        import winpty  # type: ignore

        shell = os.environ.get("COMSPEC", "powershell.exe")
        self._proc = winpty.PtyProcess.spawn(shell, cwd=str(self.cwd), dimensions=(24, 80))
        self.alive = True
        self._reader = threading.Thread(target=self._read_loop, daemon=True)
        self._reader.start()

    def _read_loop(self):
        while self.alive:
            try:
                data = self._proc.read(65536)
            except EOFError:
                break
            except Exception:
                break
            if not data:
                break
            self.on_data(data)
        self.alive = False
        self.on_exit()

    def write(self, data: str):
        if self.alive:
            try:
                self._proc.write(data)
            except Exception:
                pass

    def resize(self, cols: int, rows: int):
        if self.alive:
            try:
                self._proc.setwinsize(rows, cols)
            except Exception:
                pass

    def stop(self):
        self.alive = False
        try:
            self._proc.terminate(force=True)
        except Exception:
            pass


class WindowsPipeSession(TerminalSession):
    """
    Best-effort fallback when pywinpty isn't installed on Windows.

    Not a real PTY: no readline echo/arrow-key editing happens locally, but
    command output still streams live, line by line, as it's produced.
    Install `pywinpty` for a real interactive terminal on Windows.
    """

    def start(self):
        import subprocess

        self._proc = subprocess.Popen(
            ["powershell", "-NoLogo", "-NoExit", "-ExecutionPolicy", "Bypass"],
            cwd=str(self.cwd),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )
        self.alive = True
        self.on_data(
            "[Bob IDE] pywinpty not installed - using a limited fallback shell.\r\n"
            "[Bob IDE] Run 'pip install pywinpty' for a real interactive terminal.\r\n"
        )
        self._reader = threading.Thread(target=self._read_loop, daemon=True)
        self._reader.start()

    def _read_loop(self):
        stdout = self._proc.stdout
        while self.alive and stdout:
            line = stdout.readline()
            if not line:
                break
            self.on_data(line.replace("\n", "\r\n"))
        self.alive = False
        self.on_exit()

    def write(self, data: str):
        if self.alive and self._proc.stdin:
            try:
                if data in ("\r", "\n", "\r\n"):
                    self._proc.stdin.write("\n")
                    self._proc.stdin.flush()
                elif data == "\x03":
                    pass  # best-effort fallback can't forward signals
                else:
                    self._proc.stdin.write(data)
                    self._proc.stdin.flush()
            except (OSError, ValueError):
                pass

    def resize(self, cols: int, rows: int):
        pass

    def stop(self):
        self.alive = False
        try:
            self._proc.terminate()
        except Exception:
            pass


def create_session(terminal_id: str, cwd: Path, on_data, on_exit) -> TerminalSession:
    if IS_WINDOWS:
        try:
            import winpty  # noqa: F401
            session: TerminalSession = WindowsWinptySession(terminal_id, cwd, on_data, on_exit)
        except ImportError:
            session = WindowsPipeSession(terminal_id, cwd, on_data, on_exit)
    else:
        session = PosixPtySession(terminal_id, cwd, on_data, on_exit)
    session.start()
    return session


class SessionRegistry:
    """Tracks live terminal sessions per socket connection (sid)."""

    def __init__(self):
        self._sessions: Dict[str, TerminalSession] = {}
        self._lock = threading.Lock()

    @staticmethod
    def _key(sid: str, terminal_id: str) -> str:
        return f"{sid}:{terminal_id}"

    def create(self, sid: str, terminal_id: str, cwd: Path, on_data, on_exit) -> TerminalSession:
        key = self._key(sid, terminal_id)
        with self._lock:
            existing = self._sessions.get(key)
        if existing:
            existing.stop()
        session = create_session(terminal_id, cwd, on_data, on_exit)
        with self._lock:
            self._sessions[key] = session
        return session

    def get(self, sid: str, terminal_id: str) -> Optional[TerminalSession]:
        with self._lock:
            return self._sessions.get(self._key(sid, terminal_id))

    def remove(self, sid: str, terminal_id: str):
        key = self._key(sid, terminal_id)
        with self._lock:
            session = self._sessions.pop(key, None)
        if session:
            session.stop()

    def remove_all_for_sid(self, sid: str):
        with self._lock:
            keys = [k for k in self._sessions if k.startswith(f"{sid}:")]
            sessions = [self._sessions.pop(k) for k in keys]
        for session in sessions:
            session.stop()
