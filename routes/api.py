from flask import Blueprint, current_app, jsonify, request

from capabilities import CAPABILITIES, invoke

api_bp = Blueprint("api", __name__, url_prefix="/api")


def ok(data=None, status=200):
    return jsonify({"ok": True, "data": data or {}}), status


def fail(message, status=400):
    return jsonify({"ok": False, "error": str(message)}), status


@api_bp.get("/mcp/tools")
def mcp_tools():
    return ok({"tools": sorted(CAPABILITIES)})


@api_bp.post("/mcp/call")
def mcp_call():
    data = request.get_json(force=True)
    try:
        return ok(invoke(data.get("name", ""), data.get("arguments") or {}))
    except Exception as exc:
        return fail(exc)


@api_bp.get("/worktree/status")
def worktree_status():
    try:
        return ok(invoke("worktree.status", {"project": request.args.get("project", "sample_project")}))
    except Exception as exc:
        return fail(exc)


@api_bp.get("/worktree/diff")
def worktree_diff():
    try:
        return ok(invoke("worktree.get_diff", {
            "project": request.args.get("project", "sample_project"),
            "change_id": request.args.get("change_id", ""),
        }))
    except Exception as exc:
        return fail(exc)


def _worktree_post(tool):
    data = request.get_json(force=True)
    try:
        return ok(invoke(tool, data))
    except Exception as exc:
        return fail(exc)


@api_bp.post("/worktree/stage")
def worktree_stage():
    return _worktree_post("worktree.stage_change")


@api_bp.post("/worktree/unstage")
def worktree_unstage():
    return _worktree_post("worktree.unstage_change")


@api_bp.post("/worktree/apply")
def worktree_apply():
    return _worktree_post("worktree.apply_change")


@api_bp.post("/worktree/discard")
def worktree_discard():
    return _worktree_post("worktree.discard_change")


@api_bp.post("/worktree/snapshot")
def worktree_snapshot():
    return _worktree_post("worktree.create_snapshot")


@api_bp.get("/worktree/history")
def worktree_history():
    try:
        return ok(invoke("worktree.history", {"project": request.args.get("project", "sample_project")}))
    except Exception as exc:
        return fail(exc)


@api_bp.post("/bob/run-agent")
def bob_run_agent():
    data = request.get_json(force=True)
    try:
        return ok(invoke("model.run_agent", {
            "project": data.get("project", "sample_project"),
            "prompt": data.get("message", ""),
            "active_path": data.get("activePath"),
        }))
    except Exception as exc:
        return fail(exc)


@api_bp.get("/status")
def status():
    return ok({"socketio": bool(current_app.config.get("SOCKETIO_AVAILABLE"))})


@api_bp.get("/workspaces")
def workspaces():
    return ok(invoke("workspace.list"))


@api_bp.post("/workspace/create")
def workspace_create():
    data = request.get_json(force=True)
    try:
        return ok(invoke("workspace.create", {"name": data.get("name", "")}))
    except Exception as exc:
        return fail(exc)


@api_bp.post("/workspace/import")
def workspace_import():
    data = request.get_json(force=True)
    try:
        return ok(invoke("workspace.import", {
            "name": data.get("name", ""),
            "files": data.get("files") or [],
            "folders": data.get("folders") or [],
        }))
    except Exception as exc:
        return fail(exc)


@api_bp.get("/project/tree")
def project_tree():
    project = request.args.get("project", "sample_project")
    try:
        return ok(invoke("workspace.tree", {"project": project}))
    except Exception as exc:
        return fail(exc)


@api_bp.get("/file/read")
def file_read():
    project = request.args.get("project", "sample_project")
    path = request.args.get("path", "")
    try:
        return ok(invoke("file.read", {"project": project, "path": path}))
    except Exception as exc:
        return fail(exc)


@api_bp.post("/file/save")
def file_save():
    data = request.get_json(force=True)
    try:
        return ok(invoke("file.write", data))
    except Exception as exc:
        return fail(exc)


@api_bp.post("/file/create")
def file_create():
    data = request.get_json(force=True)
    try:
        return ok(invoke("file.create", data))
    except Exception as exc:
        return fail(exc)


@api_bp.post("/file/delete")
def file_delete():
    data = request.get_json(force=True)
    try:
        return ok(invoke("file.delete", data))
    except Exception as exc:
        return fail(exc)


@api_bp.post("/file/rename")
def file_rename():
    data = request.get_json(force=True)
    try:
        return ok(invoke("file.rename", data))
    except Exception as exc:
        return fail(exc)


@api_bp.post("/folder/create")
def folder_create():
    data = request.get_json(force=True)
    try:
        return ok(invoke("folder.create", data))
    except Exception as exc:
        return fail(exc)


@api_bp.post("/validate")
def validate_current_file():
    data = request.get_json(force=True)
    try:
        return ok(invoke("code.validate", data))
    except Exception as exc:
        return fail(exc)


@api_bp.post("/run/pytest")
def run_current_pytest():
    data = request.get_json(silent=True) or {}
    try:
        return ok(invoke("test.pytest", {"project": data.get("project", "sample_project")}))
    except Exception as exc:
        return fail(exc)


@api_bp.post("/bob/chat")
def bob_chat():
    """
    Placeholder endpoint for the Bob Assistant chat panel.

    There's no model wired up yet, so this just echoes back an
    acknowledgement with whatever context the frontend sent. The point is
    that the frontend already does a real request/response round trip here
    — wiring in an actual model later is a matter of replacing the body of
    this function with a real call, not building new plumbing.
    """
    data = request.get_json(force=True)
    try:
        return ok(invoke("assistant.chat", {
            "message": data.get("message", ""),
            "active_path": data.get("activePath"),
        }))
    except Exception as exc:
        return fail(exc)


@api_bp.get("/search")
def search():
    project = request.args.get("project", "sample_project")
    query = request.args.get("q", "")
    try:
        return ok(invoke("code.search", {"project": project, "query": query}))
    except Exception as exc:
        return fail(exc)
