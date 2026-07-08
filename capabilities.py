"""Shared Bob IDE capability registry.

Every command surface (MCP, the browser gateway, and compatibility REST
routes) calls these functions so validation and behavior cannot drift.
"""

from __future__ import annotations

import re
import shutil
import subprocess
from typing import Any, Callable

from config import WORKSPACE_DIR
from bob_core.command_runner import run_pytest, run_python
from bob_core.file_manager import (
    create_file,
    create_folder,
    delete_path,
    list_projects,
    read_file,
    rename_path,
    safe_path,
    save_file,
    scan_tree,
)
from bob_core.validator import validate_file
from bob_core.json_worktree import (
    apply_all,
    apply_change,
    create_snapshot,
    detect_manual_changes,
    discard_all,
    discard_change,
    get_diff,
    get_file_history,
    get_history,
    get_status,
    init_worktree,
    record_manual_change,
    record_rename,
    stage_all,
    stage_change,
    unstage_all,
    unstage_change,
)
from bob_core.model_service import model_run_status, start_model_run
from workspace_tools import search_workspace

Capability = Callable[..., Any]
CAPABILITIES: dict[str, Capability] = {}
_event_publisher: Callable[[str, dict[str, Any]], None] | None = None


def capability(name: str):
    def decorate(func: Capability) -> Capability:
        CAPABILITIES[name] = func
        return func

    return decorate


def invoke(name: str, arguments: dict[str, Any] | None = None) -> Any:
    try:
        func = CAPABILITIES[name]
    except KeyError as exc:
        raise ValueError(f"Unknown capability: {name}") from exc
    return func(**(arguments or {}))


def set_event_publisher(
    publisher: Callable[[str, dict[str, Any]], None] | None
) -> None:
    global _event_publisher
    _event_publisher = publisher


def _publish(event: str, payload: dict[str, Any]) -> None:
    if _event_publisher:
        _event_publisher(event, payload)


def normalize_workspace_name(name: str) -> str:
    normalized = re.sub(r"\s+", "_", name.strip())
    if not normalized:
        raise ValueError("Workspace name is required")
    if not re.fullmatch(r"[A-Za-z0-9_-]+", normalized):
        raise ValueError("Use only letters, numbers, spaces, underscores, or hyphens")
    return normalized


@capability("system.status")
def system_status() -> dict:
    """Return the IDE service and transport status."""
    return {
        "service": "Bob IDE",
        "mcp": True,
        "realtime": ["terminal", "workspace", "editor", "lsp"],
    }


@capability("workspace.list")
def workspace_list() -> dict:
    """List available workspace projects."""
    return {"projects": list_projects()}


@capability("workspace.create")
def workspace_create(name: str) -> dict:
    """Create a workspace with starter Python and test files."""
    name = normalize_workspace_name(name)
    WORKSPACE_DIR.mkdir(parents=True, exist_ok=True)
    target = WORKSPACE_DIR / name
    if target.exists():
        raise FileExistsError("Workspace already exists")
    target.mkdir(parents=True)
    (target / "main.py").write_text("print('Hello from Bob IDE')\n", encoding="utf-8")
    (target / "test.py").write_text(
        "def test_workspace_ready():\n    assert True\n", encoding="utf-8"
    )
    init_worktree(name)
    _publish("workspace:changed", {"project": name, "paths": ["main.py", "test.py"]})
    return {"project": name}


@capability("workspace.import")
def workspace_import(
    name: str, files: list[dict], folders: list[str] | None = None
) -> dict:
    """Import an in-memory folder tree into a new workspace."""
    name = normalize_workspace_name(name)
    folders = folders or []
    if not isinstance(files, list) or not isinstance(folders, list):
        raise ValueError("Invalid workspace payload")
    target = WORKSPACE_DIR / name
    if target.exists():
        raise FileExistsError("Workspace already exists")
    try:
        target.mkdir(parents=True)
        for folder in folders:
            create_folder(name, folder)
        for item in files:
            save_file(name, item.get("path", ""), item.get("content", ""))
        init_worktree(name)
    except Exception:
        if target.exists():
            shutil.rmtree(target)
        raise
    _publish(
        "workspace:changed",
        {"project": name, "paths": [item.get("path", "") for item in files]},
    )
    return {"project": name, "files": len(files), "folders": len(folders)}


@capability("workspace.tree")
def workspace_tree(project: str = "sample_project") -> dict:
    """Return the complete visible file tree for a workspace."""
    return scan_tree(project)


@capability("file.read")
def file_read(project: str, path: str) -> dict:
    """Read an editable text file."""
    return read_file(project, path)


@capability("file.write")
def file_write(project: str, path: str, content: str = "") -> dict:
    """Create or replace an editable text file."""
    init_worktree(project)
    result = save_file(project, path, content)
    change = record_manual_change(project, path)
    _publish("workspace:changed", {"project": project, "paths": [path]})
    _publish("worktree:changed", {"project": project})
    return {**result, "change": change}


@capability("file.create")
def file_create(project: str, path: str) -> dict:
    """Create an empty editable text file."""
    init_worktree(project)
    result = create_file(project, path)
    change = record_manual_change(project, path)
    _publish("workspace:changed", {"project": project, "paths": [path]})
    _publish("worktree:changed", {"project": project})
    return {**result, "change": change}


@capability("file.delete")
def file_delete(project: str, path: str) -> dict:
    """Delete a file or folder."""
    init_worktree(project)
    source = safe_path(project, path)
    file_paths = (
        [item.relative_to(safe_path(project)).as_posix() for item in source.rglob("*") if item.is_file()]
        if source.is_dir()
        else [path]
    )
    result = delete_path(project, path)
    changes = [change for item in file_paths if (change := record_manual_change(project, item))]
    _publish("workspace:changed", {"project": project, "paths": [path]})
    _publish("worktree:changed", {"project": project})
    return {**result, "changes": changes}


@capability("file.rename")
def file_rename(project: str, path: str, new_path: str) -> dict:
    """Rename or move a file or folder."""
    init_worktree(project)
    source = safe_path(project, path)
    old_files = (
        [item.relative_to(safe_path(project)).as_posix() for item in source.rglob("*") if item.is_file()]
        if source.is_dir()
        else [path]
    )
    result = rename_path(project, path, new_path)
    if len(old_files) == 1 and old_files[0] == path:
        changes = record_rename(project, path, new_path)
    else:
        changes = []
        for old_file in old_files:
            suffix = old_file[len(path):].lstrip("/")
            changes.extend(record_rename(project, old_file, f"{new_path}/{suffix}"))
    _publish("workspace:changed", {"project": project, "paths": [path, new_path]})
    _publish("worktree:changed", {"project": project})
    return {**result, "changes": changes}


@capability("folder.create")
def folder_create(project: str, path: str) -> dict:
    """Create a folder."""
    result = create_folder(project, path)
    _publish("workspace:changed", {"project": project, "paths": [path]})
    return result


@capability("code.validate")
def code_validate(path: str, content: str) -> dict:
    """Validate Python or JSON source text."""
    return {"problems": validate_file(path, content)}


@capability("code.search")
def code_search(project: str, query: str) -> dict:
    """Search text across editable workspace files."""
    return {"matches": search_workspace(query, project)}


@capability("code.run_python")
def code_run_python(project: str, path: str, timeout: int = 15) -> dict:
    """Run a Python file and return captured output."""
    return run_python(project, path, timeout)


@capability("terminal.execute")
def terminal_execute(project: str, command: str, timeout: int = 30) -> dict:
    """Run a non-interactive shell command inside a workspace."""
    from bob_core.file_manager import safe_path

    if not command.strip():
        raise ValueError("Command is required")
    try:
        result = subprocess.run(
            command,
            cwd=str(safe_path(project)),
            capture_output=True,
            text=True,
            timeout=max(1, min(timeout, 300)),
            shell=True,
        )
        return {
            "command": command,
            "returncode": result.returncode,
            "stdout": result.stdout,
            "stderr": result.stderr,
        }
    except subprocess.TimeoutExpired as exc:
        return {
            "command": command,
            "returncode": None,
            "stdout": exc.stdout or "",
            "stderr": f"Command timed out after {timeout} seconds.",
        }


@capability("test.pytest")
def test_pytest(project: str = "sample_project") -> dict:
    """Run pytest in a workspace and return its result."""
    return run_pytest(project)


@capability("assistant.chat")
def assistant_chat(message: str, active_path: str | None = None) -> dict:
    """Return the current Bob assistant response."""
    message = message.strip()
    if not message:
        raise ValueError("Message is required")
    context_note = f' (looking at "{active_path}")' if active_path else ""
    return {
        "reply": (
            "Bob isn't connected to an AI model yet, so this is a placeholder reply"
            f"{context_note}. Connect a model in the assistant.chat capability to "
            "enable real responses."
        )
    }


def _worktree_event(project: str) -> None:
    _publish("worktree:changed", {"project": project})


@capability("worktree.init")
def worktree_init(project: str) -> dict:
    result = init_worktree(project)
    _worktree_event(project)
    return result


@capability("worktree.status")
def worktree_status(project: str) -> dict:
    return detect_manual_changes(project)


@capability("worktree.get_diff")
def worktree_get_diff(project: str, change_id: str) -> dict:
    return get_diff(project, change_id)


@capability("worktree.stage_change")
def worktree_stage(project: str, change_id: str) -> dict:
    result = stage_change(project, change_id)
    _worktree_event(project)
    return result


@capability("worktree.unstage_change")
def worktree_unstage(project: str, change_id: str) -> dict:
    result = unstage_change(project, change_id)
    _worktree_event(project)
    return result


@capability("worktree.stage_all")
def worktree_stage_all(project: str) -> dict:
    result = stage_all(project)
    _worktree_event(project)
    return result


@capability("worktree.stage_many")
def worktree_stage_many(project: str, change_ids: list[str]) -> dict:
    results, errors = [], []
    for change_id in change_ids:
        try:
            results.append(stage_change(project, change_id))
        except Exception as exc:
            errors.append({"change_id": change_id, "error": str(exc)})
    _worktree_event(project)
    return {"staged": results, "errors": errors, "status": get_status(project)}


@capability("worktree.unstage_all")
def worktree_unstage_all(project: str) -> dict:
    result = unstage_all(project)
    _worktree_event(project)
    return result


@capability("worktree.unstage_many")
def worktree_unstage_many(project: str, change_ids: list[str]) -> dict:
    results, errors = [], []
    for change_id in change_ids:
        try:
            results.append(unstage_change(project, change_id))
        except Exception as exc:
            errors.append({"change_id": change_id, "error": str(exc)})
    _worktree_event(project)
    return {"unstaged": results, "errors": errors, "status": get_status(project)}


@capability("worktree.apply_change")
def worktree_apply(project: str, change_id: str) -> dict:
    result = apply_change(project, change_id)
    _publish("workspace:changed", {"project": project, "paths": [result["path"]]})
    _worktree_event(project)
    return result


@capability("worktree.apply_many")
def worktree_apply_many(project: str, change_ids: list[str], override: bool = False) -> dict:
    results, errors = [], []
    for change_id in change_ids:
        try:
            results.append(apply_change(project, change_id, override))
        except Exception as exc:
            errors.append({"change_id": change_id, "error": str(exc)})
    _publish("workspace:changed", {"project": project, "paths": [item["path"] for item in results]})
    _worktree_event(project)
    return {"applied": results, "errors": errors, "status": get_status(project)}


@capability("worktree.override_and_apply")
def worktree_override_apply(project: str, change_id: str) -> dict:
    result = apply_change(project, change_id, override=True)
    _publish("workspace:changed", {"project": project, "paths": [result["path"]]})
    _worktree_event(project)
    return result


@capability("worktree.apply_passing")
def worktree_apply_passing(project: str) -> dict:
    change_ids = [
        item["change_id"]
        for item in get_status(project)["proposed"]
        if item.get("review_status", "PASS") != "FAIL"
    ]
    return worktree_apply_many(project, change_ids)


@capability("worktree.apply_all")
def worktree_apply_all(project: str, override: bool = False) -> dict:
    result = apply_all(project, override)
    _publish("workspace:changed", {"project": project, "paths": [item["path"] for item in result["applied"]]})
    _worktree_event(project)
    return result


@capability("worktree.discard_change")
def worktree_discard(project: str, change_id: str) -> dict:
    result = discard_change(project, change_id)
    _publish("workspace:changed", {"project": project, "paths": [result["path"]]})
    _worktree_event(project)
    return result


@capability("worktree.discard_many")
def worktree_discard_many(project: str, change_ids: list[str]) -> dict:
    results, errors = [], []
    for change_id in change_ids:
        try:
            results.append(discard_change(project, change_id))
        except Exception as exc:
            errors.append({"change_id": change_id, "error": str(exc)})
    _publish("workspace:changed", {"project": project, "paths": [item["path"] for item in results]})
    _worktree_event(project)
    return {"discarded": results, "errors": errors, "status": get_status(project)}


@capability("worktree.discard_all")
def worktree_discard_all(project: str) -> dict:
    result = discard_all(project)
    _publish("workspace:changed", {"project": project, "paths": []})
    _worktree_event(project)
    return result


@capability("worktree.create_snapshot")
def worktree_snapshot(project: str, label: str | None = None, message: str | None = None) -> dict:
    result = create_snapshot(project, label, message)
    _worktree_event(project)
    return result


@capability("worktree.history")
def worktree_history(project: str) -> dict:
    return get_history(project)


@capability("worktree.file_history")
def worktree_file_history(project: str, path: str) -> dict:
    return get_file_history(project, path)


@capability("worktree.file_status")
def worktree_file_status(project: str, path: str) -> dict:
    status = get_status(project)
    matches = []
    for group in ("conflicts", "proposed", "changes", "staged"):
        matches.extend({**item, "group": group} for item in status[group] if item["path"] == path)
    return {"project": project, "path": path, "changes": matches}


@capability("worktree.get_hunks")
def worktree_get_hunks(project: str, change_id: str) -> dict:
    diff = get_diff(project, change_id)
    return {"project": project, "change_id": change_id, "hunks": diff.get("hunks", [])}


@capability("worktree.generate_checkpoint_message")
def worktree_generate_checkpoint_message(project: str) -> dict:
    status = get_status(project)
    staged = status["staged"]
    if not staged:
        return {"message": "Checkpoint"}
    actions = {"add": "Add", "modify": "Update", "delete": "Remove"}
    first = staged[0]
    if len(staged) == 1:
        return {"message": f"{actions.get(first['action'], 'Update')} {first['path']}"}
    return {"message": f"Update {len(staged)} files"}


@capability("model.plan")
def model_plan(project: str, prompt: str, active_path: str | None = None) -> dict:
    return start_model_run(project, prompt, "plan", active_path)


@capability("model.run_agent")
def model_run_agent(project: str, prompt: str, active_path: str | None = None) -> dict:
    return start_model_run(project, prompt, "agent", active_path)


@capability("model.run_status")
def model_status(project: str, run_id: str) -> dict:
    return model_run_status(project, run_id)
