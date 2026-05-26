from flask import Flask, jsonify, render_template, request
from config import WORKSPACE_DIR
from bob_core.file_manager import list_projects, scan_tree, read_file, save_file, create_file, create_folder
from bob_core.validator import validate_file
from bob_core.command_runner import run_python, stop_python

app = Flask(__name__)


def ok(data=None, status=200):
    return jsonify({"ok": True, "data": data or {}}), status


def fail(message, status=400):
    return jsonify({"ok": False, "error": str(message)}), status


@app.route("/")
def index():
    return render_template("index.html")


@app.get("/api/workspaces")
def workspaces():
    return ok({"projects": list_projects()})


@app.post("/api/workspace/create")
def workspace_create():
    data = request.get_json(force=True)
    name = data.get("name", "").strip().replace(" ", "_")
    if not name:
        return fail("Workspace name is required")
    target = WORKSPACE_DIR / name
    if target.exists():
        return fail("Workspace already exists")
    target.mkdir(parents=True)
    return ok({"project": name})


@app.get("/api/project/tree")
def project_tree():
    project = request.args.get("project", "sample_project")
    try:
        return ok(scan_tree(project))
    except Exception as exc:
        return fail(exc)


@app.get("/api/file/read")
def file_read():
    project = request.args.get("project", "sample_project")
    path = request.args.get("path", "")
    try:
        return ok(read_file(project, path))
    except Exception as exc:
        return fail(exc)


@app.post("/api/file/save")
def file_save():
    data = request.get_json(force=True)
    try:
        return ok(save_file(data["project"], data["path"], data.get("content", "")))
    except Exception as exc:
        return fail(exc)


@app.post("/api/file/create")
def file_create():
    data = request.get_json(force=True)
    try:
        return ok(create_file(data["project"], data["path"]))
    except Exception as exc:
        return fail(exc)


@app.post("/api/folder/create")
def folder_create():
    data = request.get_json(force=True)
    try:
        return ok(create_folder(data["project"], data["path"]))
    except Exception as exc:
        return fail(exc)


@app.post("/api/validate")
def validate_current_file():
    data = request.get_json(force=True)
    try:
        problems = validate_file(data.get("path", ""), data.get("content", ""))
        return ok({"problems": problems})
    except Exception as exc:
        return fail(exc)


@app.post("/api/run/python")
def run_current_python():
    data = request.get_json(force=True)
    try:
        return ok(run_python(data["project"], data["path"]))
    except Exception as exc:
        return fail(exc)


@app.post("/api/run/stop")
def stop_current_python():
    data = request.get_json(force=True)
    try:
        return ok(stop_python(data["project"], data["path"]))
    except Exception as exc:
        return fail(exc)


if __name__ == "__main__":
    app.run(debug=False, port=5000)
