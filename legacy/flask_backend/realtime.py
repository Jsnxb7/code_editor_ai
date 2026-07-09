"""
Socket.IO wiring for Bob IDE's real-time terminal + LSP proxy.

Terminal Protocol (client -> server):
  terminal:create  { terminalId, project }
  terminal:input   { terminalId, data }
  terminal:resize  { terminalId, cols, rows }
  terminal:dispose { terminalId }

Terminal Protocol (server -> client):
  terminal:ready   { terminalId, cwd }
  terminal:data    { terminalId, data }
  terminal:exit    { terminalId }
  terminal:error   { terminalId, message }

LSP Protocol is handled in routes/lsp.py via the /lsp namespace.
"""

import threading
import time

from bob_core.file_manager import safe_path
from capabilities import set_event_publisher
from bob_core.model_service import set_model_event_publisher
from config import IGNORED_DIRS, WORKSPACE_DIR
from terminal_session import SessionRegistry

try:
    from flask import request
    from flask_socketio import SocketIO, emit, join_room, leave_room
except ImportError:
    request = None
    emit = None
    SocketIO = None

# Werkzeug's dev server often fails direct websocket upgrades on Windows.
# Bob uses MCP/JSON polling for realtime source control, so Socket.IO is kept
# on long-polling transport for terminal/editor/model convenience events.
socketio = SocketIO(
    cors_allowed_origins="*",
    async_mode="threading",
    allow_upgrades=False,
) if SocketIO else None
registry = SessionRegistry()
_watcher_started = False


def init_realtime(app):
    if not socketio:
        app.config["SOCKETIO_AVAILABLE"] = False
        return None

    app.config["SOCKETIO_AVAILABLE"] = True
    socketio.init_app(app)
    set_event_publisher(
        lambda event, payload: socketio.emit(
            event,
            payload,
            room=f"workspace:{payload['project']}",
        )
    )
    set_model_event_publisher(
        lambda event, payload: socketio.emit(
            event,
            payload,
            room=f"workspace:{payload['project']}",
        )
    )
    register_terminal_events()
    register_workspace_events()
    start_workspace_watcher()

    # Register LSP Socket.IO events on the /lsp namespace
    try:
        from routes.lsp import register_lsp_events
        register_lsp_events(socketio)
    except Exception as exc:
        import logging
        logging.getLogger(__name__).warning("LSP not available: %s", exc)

    return socketio


def register_terminal_events():
    @socketio.on("connect")
    def on_connect():
        emit("connection:ready", {})

    @socketio.on("terminal:create")
    def terminal_create(data):
        sid = request.sid
        data = data or {}
        terminal_id = str(data.get("terminalId", "default"))
        project = data.get("project", "sample_project")

        try:
            cwd = safe_path(project)
        except ValueError as exc:
            emit("terminal:error", {"terminalId": terminal_id, "message": str(exc)})
            return

        def on_data(text, _sid=sid, _tid=terminal_id):
            socketio.emit("terminal:data", {"terminalId": _tid, "data": text}, to=_sid)

        def on_exit(_sid=sid, _tid=terminal_id):
            socketio.emit("terminal:exit", {"terminalId": _tid}, to=_sid)

        try:
            registry.create(sid, terminal_id, cwd, on_data, on_exit)
        except Exception as exc:
            emit("terminal:error", {"terminalId": terminal_id, "message": str(exc)})
            return

        emit("terminal:ready", {"terminalId": terminal_id, "cwd": str(cwd)})

    @socketio.on("terminal:input")
    def terminal_input(data):
        sid = request.sid
        data = data or {}
        terminal_id = str(data.get("terminalId", "default"))
        text = data.get("data", "")
        session = registry.get(sid, terminal_id)
        if session:
            session.write(text)

    @socketio.on("terminal:resize")
    def terminal_resize(data):
        sid = request.sid
        data = data or {}
        terminal_id = str(data.get("terminalId", "default"))
        cols = int(data.get("cols", 80))
        rows = int(data.get("rows", 24))
        session = registry.get(sid, terminal_id)
        if session:
            session.resize(cols, rows)

    @socketio.on("terminal:dispose")
    def terminal_dispose(data):
        sid = request.sid
        terminal_id = str((data or {}).get("terminalId", "default"))
        registry.remove(sid, terminal_id)

    @socketio.on("disconnect")
    def on_disconnect():
        registry.remove_all_for_sid(request.sid)


def register_workspace_events():
    @socketio.on("workspace:join")
    def workspace_join(data):
        project = str((data or {}).get("project", ""))
        if project:
            safe_path(project)
            join_room(f"workspace:{project}")
            emit("workspace:ready", {"project": project})

    @socketio.on("workspace:leave")
    def workspace_leave(data):
        project = str((data or {}).get("project", ""))
        if project:
            leave_room(f"workspace:{project}")

    @socketio.on("editor:change")
    def editor_change(data):
        data = data or {}
        project = str(data.get("project", ""))
        path = str(data.get("path", ""))
        if not project or not path:
            return
        safe_path(project, path)
        socketio.emit(
            "editor:change",
            {
                "project": project,
                "path": path,
                "content": str(data.get("content", "")),
                "clientId": str(data.get("clientId", "")),
                "version": int(data.get("version", 0)),
            },
            room=f"workspace:{project}",
            include_self=False,
        )


def _workspace_snapshot():
    snapshot = {}
    if not WORKSPACE_DIR.exists():
        return snapshot
    for project_dir in WORKSPACE_DIR.iterdir():
        if not project_dir.is_dir():
            continue
        files = {}
        for path in project_dir.rglob("*"):
            if not path.is_file():
                continue
            rel = path.relative_to(project_dir)
            if any(part in IGNORED_DIRS for part in rel.parts):
                continue
            try:
                stat = path.stat()
                files[rel.as_posix()] = (stat.st_mtime_ns, stat.st_size)
            except OSError:
                continue
        snapshot[project_dir.name] = files
    return snapshot


def start_workspace_watcher():
    global _watcher_started
    if _watcher_started:
        return
    _watcher_started = True

    def watch():
        previous = _workspace_snapshot()
        while True:
            time.sleep(0.2)
            current = _workspace_snapshot()
            for project in set(previous) | set(current):
                before = previous.get(project, {})
                after = current.get(project, {})
                changed = sorted(
                    path
                    for path in set(before) | set(after)
                    if before.get(path) != after.get(path)
                )
                if changed:
                    socketio.emit(
                        "workspace:changed",
                        {"project": project, "paths": changed},
                        room=f"workspace:{project}",
                    )
            previous = current

    threading.Thread(target=watch, name="workspace-watcher", daemon=True).start()
