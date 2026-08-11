"""Shared Bob IDE capability registry.

Every command surface (MCP, the browser gateway, and compatibility REST
routes) calls these functions so validation and behavior cannot drift.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import hashlib
import json
from typing import Any, Callable

from config import WORKSPACE_DIR
from bob_core.command_runner import run_pytest, run_python, stop_python
from bob_core.execution_env import workspace_process_env
from bob_core.file_manager import (
    create_file,
    create_folder,
    delete_path,
    list_files,
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
    apply_all_hunks,
    apply_change,
    apply_hunk,
    compare_with_snapshot,
    create_snapshot,
    detect_manual_changes,
    discard_all,
    discard_change,
    discard_hunk,
    get_diff,
    get_file_history,
    get_history,
    get_status,
    get_indexed_changes,
    get_timeline,
    ignore_path,
    init_worktree,
    record_manual_change,
    record_rename,
    restore_file,
    restore_snapshot,
    stage_all,
    stage_change,
    stage_hunk,
    unstage_all,
    unstage_change,
)
from bob_core.model_service import model_run_status, plan_stage, replan_stage, code_stage, review_stage, direct_code_review_stage, run_agent_stage
from bob_core.model_queue import FairModelQueue
from bob_core.colab_adapter import ColabAdapter, ColabRetryError
from bob_core.model_config import read_model_config, save_model_config
from bob_core import git_service
from bob_core import proposal_store
from bob_core import plan_store
from bob_core.context_builder import build_context as build_model_context
from bob_core.git_migration import migrate_json_worktree
from workspace_tools import search_workspace

Capability = Callable[..., Any]
CAPABILITIES: dict[str, Capability] = {}
_event_publisher: Callable[[str, dict[str, Any]], None] | None = None


def capability(name: str):
    def decorate(func: Capability) -> Capability:
        if not (func.__doc__ or "").strip():
            func.__doc__ = f"Bob IDE capability: {name.replace('.', ' ').replace('_', ' ')}."
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


MODEL_QUEUE = FairModelQueue(on_change=lambda snapshot: _publish("model:queue", {
    "lane_count": 1,
    "model_busy": snapshot.get("model_busy", False),
    "queue_depth": snapshot.get("queue_depth", 0),
    "total_depth": snapshot.get("total_depth", 0),
}))


def _queued_model_call(
    tool: str,
    project: str | None,
    actor_user_id: str | None,
    request_id: str | None,
    operation: Callable[[], Any],
) -> Any:
    return MODEL_QUEUE.run(
        actor_user_id=actor_user_id,
        workspace_id=project,
        request_id=request_id,
        tool=tool,
        operation=operation,
    )


def normalize_workspace_name(name: str) -> str:
    normalized = re.sub(r"\s+", "_", name.strip())
    if not normalized:
        raise ValueError("Workspace name is required")
    if not re.fullmatch(r"[A-Za-z0-9_-]+", normalized):
        raise ValueError("Use only letters, numbers, spaces, underscores, or hyphens")
    return normalized


def normalize_workspace_scope(scope: str | None) -> str | None:
    if scope is None:
        return None
    normalized = str(scope).strip()
    if not re.fullmatch(r"[a-z0-9._-]{3,32}--[0-9a-f-]{36}", normalized):
        raise ValueError("Invalid user workspace scope")
    return normalized


def scoped_project(name: str, scope: str | None = None) -> str:
    name = normalize_workspace_name(name)
    normalized_scope = normalize_workspace_scope(scope)
    return f"{normalized_scope}/{name}" if normalized_scope else name


@capability("system.status")
def system_status() -> dict:
    """Return the IDE service and transport status."""
    return {
        "service": "Bob IDE",
        "mcp": True,
        "realtime": ["terminal", "workspace", "editor", "lsp", "git", "proposal", "model"],
        "command_plane": "MCP capability registry",
        "source_control": "Git with Bob proposal store",
    }


@capability("workspace.list")
def workspace_list(scope: str | None = None) -> dict:
    """List available workspace projects."""
    normalized_scope = normalize_workspace_scope(scope)
    if normalized_scope:
        user_root = WORKSPACE_DIR / normalized_scope
        user_root.mkdir(parents=True, exist_ok=True)
        return {"projects": sorted(item.name for item in user_root.iterdir() if item.is_dir())}
    return {"projects": list_projects()}


@capability("workspace.create")
def workspace_create(name: str, scope: str | None = None) -> dict:
    """Create a workspace with starter Python and test files."""
    name = normalize_workspace_name(name)
    project = scoped_project(name, scope)
    WORKSPACE_DIR.mkdir(parents=True, exist_ok=True)
    target = WORKSPACE_DIR / project
    if target.exists():
        raise FileExistsError("Workspace already exists")
    target.mkdir(parents=True)
    (target / "main.py").write_text("print('Hello from Bob IDE')\n", encoding="utf-8")
    (target / "test.py").write_text(
        "def test_workspace_ready():\n    assert True\n", encoding="utf-8"
    )
    git_service.init_repo(project)
    _publish("workspace:changed", {"project": name, "paths": ["main.py", "test.py"]})
    return {"project": name}


@capability("workspace.import")
def workspace_import(
    name: str, files: list[dict], folders: list[str] | None = None, scope: str | None = None
) -> dict:
    """Import an in-memory folder tree into a new workspace."""
    name = normalize_workspace_name(name)
    project = scoped_project(name, scope)
    folders = folders or []
    if not isinstance(files, list) or not isinstance(folders, list):
        raise ValueError("Invalid workspace payload")
    target = WORKSPACE_DIR / project
    if target.exists():
        raise FileExistsError("Workspace already exists")
    try:
        target.mkdir(parents=True)
        for folder in folders:
            create_folder(project, folder)
        for item in files:
            save_file(project, item.get("path", ""), item.get("content", ""))
        git_service.init_repo(project)
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


@capability("workspace.list_files")
def workspace_list_files(project: str = "sample_project") -> dict:
    """List editable files in a workspace."""
    return {"files": list_files(project)}


@capability("file.read")
def file_read(project: str, path: str) -> dict:
    """Read an editable text file."""
    return read_file(project, path)


@capability("file.write")
def file_write(project: str, path: str, content: str = "") -> dict:
    """Create or replace an editable text file."""
    result = save_file(project, path, content)
    _publish("workspace:changed", {"project": project, "paths": [path]})
    _source_control_event(project)
    return result


@capability("file.create")
def file_create(project: str, path: str) -> dict:
    """Create an empty editable text file."""
    result = create_file(project, path)
    _publish("workspace:changed", {"project": project, "paths": [path]})
    _source_control_event(project)
    return result


@capability("file.delete")
def file_delete(project: str, path: str) -> dict:
    """Delete a file or folder."""
    source = safe_path(project, path)
    result = delete_path(project, path)
    _publish("workspace:changed", {"project": project, "paths": [path]})
    _source_control_event(project)
    return result


@capability("file.rename")
def file_rename(project: str, path: str, new_path: str) -> dict:
    """Rename or move a file or folder."""
    result = rename_path(project, path, new_path)
    _publish("workspace:changed", {"project": project, "paths": [path, new_path]})
    _source_control_event(project)
    return result


@capability("folder.create")
def folder_create(project: str, path: str) -> dict:
    """Create a folder."""
    result = create_folder(project, path)
    _publish("workspace:changed", {"project": project, "paths": [path]})
    _source_control_event(project)
    return result


@capability("folder.delete")
def folder_delete(project: str, path: str) -> dict:
    """Delete a workspace folder and record its file changes."""
    return file_delete(project, path)


@capability("folder.rename")
def folder_rename(project: str, path: str, new_path: str) -> dict:
    """Rename a workspace folder and record its file changes."""
    return file_rename(project, path, new_path)


@capability("code.validate")
def code_validate(path: str, content: str) -> dict:
    """Validate Python or JSON source text."""
    return {"problems": validate_file(path, content)}


@capability("code.search")
def code_search(project: str, query: str) -> dict:
    """Search text across editable workspace files."""
    return {"matches": search_workspace(query, project)}


@capability("code.run_python")
def code_run_python(project: str, path: str, timeout: int = 15, actor_user_id: str | None = None) -> dict:
    """Run a Python file and return captured output."""
    return run_python(project, path, timeout, actor_user_id)


@capability("code.stop_python")
def code_stop_python(project: str, path: str) -> dict:
    """Stop a Python process previously started for a file."""
    return stop_python(project, path)


@capability("terminal.execute")
def terminal_execute(project: str, command: str, timeout: int = 30, actor_user_id: str | None = None) -> dict:
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
            env=workspace_process_env(project, actor_user_id),
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
def test_pytest(project: str = "sample_project", actor_user_id: str | None = None) -> dict:
    """Run pytest in a workspace and return its result."""
    return run_pytest(project, actor_user_id)


def _limited_model_context(project: str, active_path: str | None = None, budget: int = 160_000) -> dict:
    """Build the same lightweight context shape used by MCP/model calls."""
    paths = []
    try:
        paths = [item for item in scan_tree(project).get("children", [])]
    except Exception:
        paths = []
    from bob_core.file_manager import list_files

    file_paths = list_files(project)
    ordered = []
    if active_path and active_path in file_paths:
        ordered.append(active_path)
    ordered.extend(path for path in file_paths if path not in ordered)
    files: dict[str, str] = {}
    total = 0
    for path in ordered:
        try:
            content = read_file(project, path)["content"]
        except Exception:
            continue
        if total + len(content) > budget:
            break
        files[path] = content
        total += len(content)
    return {"workspace_tree": scan_tree(project), "files": files}


@capability("assistant.chat")
def assistant_chat(message: str, project: str = "sample_project", active_path: str | None = None) -> dict:
    """Chat through the shared MCP capability layer.

    If a Colab endpoint is configured, the chat mode asks the planner endpoint
    for a structured coding answer without creating file proposals. Without
    Colab, it returns a useful local response explaining how to run Plan/Run.
    """
    message = message.strip()
    if not message:
        raise ValueError("Message is required")
    adapter = ColabAdapter()
    if adapter.configured:
        payload = {
            "run_id": "chat_preview",
            "project": project,
            "user_prompt": message,
            "active_path": active_path,
            **_limited_model_context(project, active_path),
        }
        plan = adapter.plan(payload)
        reply = plan.get("summary") or "I prepared a plan for this request."
        if plan.get("files_needed"):
            reply += "\n\nLikely files: " + ", ".join(plan["files_needed"])
        if plan.get("coder_prompt"):
            reply += "\n\nNext step: switch to Run mode to create reviewable proposals."
        return {"reply": reply, "plan": plan, "provider": "colab"}
    context_note = f' while looking at `{active_path}`' if active_path else ""
    return {
        "reply": (
            f"I am routed through the MCP capability layer{context_note}. "
            "Set BOB_COLAB_BASE_URL to enable live model chat, or use Plan/Run to queue a Colab-powered model job. "
            "All generated edits will appear as Source Control proposals before they touch files."
        ),
        "provider": "local_contract_stub",
    }


def _worktree_event(project: str) -> None:
    _publish("worktree:changed", {"project": project})


def _source_control_event(project: str, event: str = "git:changed") -> None:
    _publish(event, {"project": project})
    _publish("source-control:changed", {"project": project})
    _worktree_event(project)


def _parse_source_id(change_id: str) -> dict[str, str]:
    if change_id.startswith("proposal:"):
        _, proposal_id, path = change_id.split(":", 2)
        return {"source": "proposal", "proposal_id": proposal_id, "path": path}
    if change_id.startswith("git:"):
        _, group, path = change_id.split(":", 2)
        return {"source": "git", "group": group, "path": path}
    return {"source": "legacy", "change_id": change_id}


def _combined_status(project: str) -> dict:
    if not git_service.is_git_repo(project)["is_repo"]:
        migrate_json_worktree(project)
    status = git_service.get_status(project)
    proposal_rows = proposal_store.proposal_rows(project)
    proposal_conflicts = [item for item in proposal_rows if item["status"] == "conflict"]
    proposals = [item for item in proposal_rows if item["status"] != "conflict"]
    conflicts = [*status["conflicts"], *proposal_conflicts]
    summary = {
        "conflicts": len(conflicts),
        "proposed": len(proposals),
        "changes": len(status["changes"]),
        "untracked": len(status["untracked"]),
        "staged": len(status["staged"]),
    }
    revision_source = json.dumps({
        "head": status.get("head"),
        "branch": status.get("branch"),
        "summary": summary,
        "rows": [
            item["change_id"]
            for group in (conflicts, proposals, status["changes"], status["untracked"], status["staged"])
            for item in group
        ],
    }, sort_keys=True)
    return {
        **status,
        "state": "clean" if not sum(summary.values()) else "conflict" if conflicts else "dirty",
        "summary": summary,
        "conflicts": conflicts,
        "proposed": proposals,
        "revision": hashlib.sha256(revision_source.encode()).hexdigest(),
        "active_snapshot": status.get("head", "")[:8] if status.get("head") else None,
        "active_worktree": status.get("branch") or "main",
    }


@capability("git.is_repo")
def git_is_repo(project: str) -> dict:
    return git_service.is_git_repo(project)


@capability("git.init")
def git_init(project: str) -> dict:
    result = git_service.init_repo(project)
    _source_control_event(project)
    return result


@capability("git.status")
def git_status(project: str) -> dict:
    return git_service.get_status(project)


@capability("git.diff")
def git_diff(project: str, path: str, staged: bool = False, conflict: bool = False) -> dict:
    return git_service.get_diff(project, path, staged, conflict)


@capability("git.stage")
def git_stage(project: str, path: str) -> dict:
    result = git_service.stage_file(project, path)
    _source_control_event(project)
    return result


@capability("git.unstage")
def git_unstage(project: str, path: str) -> dict:
    result = git_service.unstage_file(project, path)
    _source_control_event(project)
    return result


@capability("git.stage_all")
def git_stage_all_capability(project: str) -> dict:
    result = git_service.stage_all(project)
    _source_control_event(project)
    return result


@capability("git.unstage_all")
def git_unstage_all_capability(project: str) -> dict:
    result = git_service.unstage_all(project)
    _source_control_event(project)
    return result


@capability("git.stage_hunk")
def git_stage_hunk(project: str, path: str, hunk_id: str) -> dict:
    result = git_service.stage_hunk(project, path, hunk_id)
    _source_control_event(project)
    return result


@capability("git.discard_hunk")
def git_discard_hunk(project: str, path: str, hunk_id: str) -> dict:
    result = git_service.discard_hunk(project, path, hunk_id)
    _publish("workspace:changed", {"project": project, "paths": [path]})
    _source_control_event(project)
    return result


@capability("git.discard")
def git_discard(project: str, path: str, staged: bool = False, untracked: bool = False) -> dict:
    result = git_service.discard_file(project, path, staged=staged, untracked=untracked)
    _publish("workspace:changed", {"project": project, "paths": [path]})
    _source_control_event(project)
    return result


@capability("git.discard_all")
def git_discard_all_capability(project: str, include_untracked: bool = False) -> dict:
    result = git_service.discard_all(project, include_untracked)
    _publish("workspace:changed", {"project": project, "paths": []})
    _source_control_event(project)
    return result


@capability("git.commit")
def git_commit(project: str, message: str) -> dict:
    result = git_service.commit(project, message)
    _source_control_event(project)
    return result


@capability("git.identity")
def git_identity(project: str) -> dict:
    return git_service.get_identity(project)


@capability("git.set_identity")
def git_set_identity(project: str, name: str, email: str) -> dict:
    return git_service.set_identity(project, name, email)


@capability("git.branches")
def git_branches(project: str) -> dict:
    return git_service.list_branches(project)


@capability("git.create_branch")
def git_create_branch(project: str, name: str, checkout: bool = True) -> dict:
    result = git_service.create_branch(project, name, checkout)
    _source_control_event(project)
    return result


@capability("git.checkout")
def git_checkout(project: str, name: str) -> dict:
    result = git_service.checkout_branch(project, name)
    _publish("workspace:changed", {"project": project, "paths": []})
    _source_control_event(project)
    return result


@capability("git.log")
def git_log(project: str, limit: int = 50) -> dict:
    return git_service.get_log(project, limit)


@capability("git.file_history")
def git_file_history(project: str, path: str, limit: int = 50) -> dict:
    return git_service.get_file_history(project, path, limit)


@capability("git.restore_file")
def git_restore_file(project: str, path: str, ref: str = "HEAD") -> dict:
    result = git_service.restore_file(project, path, ref)
    _publish("workspace:changed", {"project": project, "paths": [path]})
    _source_control_event(project)
    return result


@capability("git.conflicts")
def git_conflicts(project: str) -> dict:
    return git_service.get_conflicts(project)


@capability("git.accept_current")
def git_accept_current(project: str, path: str) -> dict:
    result = git_service.accept_conflict(project, path, "ours")
    _publish("workspace:changed", {"project": project, "paths": [path]})
    _source_control_event(project)
    return result


@capability("git.accept_incoming")
def git_accept_incoming(project: str, path: str) -> dict:
    result = git_service.accept_conflict(project, path, "theirs")
    _publish("workspace:changed", {"project": project, "paths": [path]})
    _source_control_event(project)
    return result


@capability("git.generate_commit_message")
def git_generate_commit_message(project: str) -> dict:
    return git_service.generate_commit_message(project)


@capability("proposal.list")
def proposal_list(project: str, include_inactive: bool = False) -> dict:
    return proposal_store.list_proposals(project, include_inactive)


@capability("proposal.diff")
def proposal_diff(project: str, proposal_id: str, path: str) -> dict:
    return proposal_store.get_diff(project, proposal_id, path)


@capability("proposal.preview")
def proposal_preview(project: str, proposal_id: str, path: str) -> dict:
    return proposal_store.get_preview(project, proposal_id, path)


@capability("proposal.apply")
def proposal_apply(project: str, proposal_id: str, path: str | None = None) -> dict:
    result = proposal_store.apply_proposal(project, proposal_id, path)
    _publish("workspace:changed", {"project": project, "paths": result["applied"]})
    _source_control_event(project, "proposal:changed")
    return result


@capability("proposal.override_apply")
def proposal_override_apply(project: str, proposal_id: str, path: str | None = None) -> dict:
    result = proposal_store.apply_proposal(project, proposal_id, path, override=True)
    _publish("workspace:changed", {"project": project, "paths": result["applied"]})
    _source_control_event(project, "proposal:changed")
    return result


@capability("proposal.apply_all")
def proposal_apply_all(project: str, only_passing: bool = True) -> dict:
    result = proposal_store.apply_all(project, only_passing)
    paths = [path for item in result["results"] for path in item["applied"]]
    _publish("workspace:changed", {"project": project, "paths": paths})
    _source_control_event(project, "proposal:changed")
    return result


@capability("proposal.discard")
def proposal_discard(project: str, proposal_id: str, path: str | None = None) -> dict:
    result = proposal_store.discard_proposal(project, proposal_id, path)
    _source_control_event(project, "proposal:changed")
    return result


@capability("proposal.discard_all")
def proposal_discard_all(project: str) -> dict:
    result = proposal_store.discard_all(project)
    _source_control_event(project, "proposal:changed")
    return result


@capability("worktree.init")
def worktree_init(project: str) -> dict:
    result = git_service.init_repo(project)
    _source_control_event(project)
    return result


@capability("worktree.status")
def worktree_status(project: str) -> dict:
    """Compatibility status backed by Git and Bob proposals."""
    return _combined_status(project)


@capability("worktree.scan")
def worktree_scan(project: str) -> dict:
    return _combined_status(project)




@capability("worktree.indexed_changes")
def worktree_indexed_changes(project: str) -> dict:
    return {
        "project": project,
        "git": git_service.get_status(project),
        "proposals": proposal_store.list_proposals(project, include_inactive=True)["proposals"],
    }


@capability("worktree.get_diff")
def worktree_get_diff(project: str, change_id: str) -> dict:
    parsed = _parse_source_id(change_id)
    if parsed["source"] == "proposal":
        return proposal_store.get_diff(project, parsed["proposal_id"], parsed["path"])
    if parsed["source"] == "git":
        return git_service.get_diff(
            project,
            parsed["path"],
            staged=parsed["group"] == "staged",
            conflict=parsed["group"] == "conflicts",
        )
    return get_diff(project, change_id)


@capability("worktree.stage_change")
def worktree_stage(project: str, change_id: str) -> dict:
    parsed = _parse_source_id(change_id)
    if parsed["source"] != "git":
        raise ValueError("Only Git changes can be staged")
    git_service.stage_file(project, parsed["path"])
    _source_control_event(project)
    return _combined_status(project)


@capability("worktree.unstage_change")
def worktree_unstage(project: str, change_id: str) -> dict:
    parsed = _parse_source_id(change_id)
    if parsed["source"] != "git":
        raise ValueError("Only Git changes can be unstaged")
    git_service.unstage_file(project, parsed["path"])
    _source_control_event(project)
    return _combined_status(project)


@capability("worktree.stage_all")
def worktree_stage_all(project: str) -> dict:
    git_service.stage_all(project)
    _source_control_event(project)
    return _combined_status(project)


@capability("worktree.stage_many")
def worktree_stage_many(project: str, change_ids: list[str]) -> dict:
    results, errors = [], []
    for change_id in change_ids:
        try:
            parsed = _parse_source_id(change_id)
            results.append(git_service.stage_file(project, parsed["path"]))
        except Exception as exc:
            errors.append({"change_id": change_id, "error": str(exc)})
    _source_control_event(project)
    return {"staged": results, "errors": errors, "status": _combined_status(project)}


@capability("worktree.unstage_all")
def worktree_unstage_all(project: str) -> dict:
    git_service.unstage_all(project)
    _source_control_event(project)
    return _combined_status(project)


@capability("worktree.unstage_many")
def worktree_unstage_many(project: str, change_ids: list[str]) -> dict:
    results, errors = [], []
    for change_id in change_ids:
        try:
            parsed = _parse_source_id(change_id)
            results.append(git_service.unstage_file(project, parsed["path"]))
        except Exception as exc:
            errors.append({"change_id": change_id, "error": str(exc)})
    _source_control_event(project)
    return {"unstaged": results, "errors": errors, "status": _combined_status(project)}


@capability("worktree.apply_change")
def worktree_apply(project: str, change_id: str) -> dict:
    parsed = _parse_source_id(change_id)
    if parsed["source"] != "proposal":
        raise ValueError("Only Bob proposals can be applied")
    result = proposal_store.apply_proposal(project, parsed["proposal_id"], parsed["path"])
    _publish("workspace:changed", {"project": project, "paths": result["applied"]})
    _source_control_event(project, "proposal:changed")
    return {**result, "path": parsed["path"]}


@capability("worktree.apply_many")
def worktree_apply_many(project: str, change_ids: list[str], override: bool = False) -> dict:
    results, errors = [], []
    for change_id in change_ids:
        try:
            parsed = _parse_source_id(change_id)
            results.append(proposal_store.apply_proposal(project, parsed["proposal_id"], parsed["path"], override))
        except Exception as exc:
            errors.append({"change_id": change_id, "error": str(exc)})
    paths = [path for item in results for path in item["applied"]]
    _publish("workspace:changed", {"project": project, "paths": paths})
    _source_control_event(project, "proposal:changed")
    return {"applied": results, "errors": errors, "status": _combined_status(project)}


@capability("worktree.override_and_apply")
def worktree_override_apply(project: str, change_id: str) -> dict:
    parsed = _parse_source_id(change_id)
    result = proposal_store.apply_proposal(project, parsed["proposal_id"], parsed["path"], override=True)
    _publish("workspace:changed", {"project": project, "paths": result["applied"]})
    _source_control_event(project, "proposal:changed")
    return {**result, "path": parsed["path"]}


@capability("worktree.apply_passing")
def worktree_apply_passing(project: str) -> dict:
    return proposal_apply_all(project, only_passing=True)


@capability("worktree.apply_all")
def worktree_apply_all(project: str, override: bool = False) -> dict:
    if override:
        results = [
            proposal_store.apply_proposal(project, item["proposal_id"], override=True)
            for item in proposal_store.list_proposals(project)["proposals"]
        ]
        paths = [path for item in results for path in item["applied"]]
        _publish("workspace:changed", {"project": project, "paths": paths})
        _source_control_event(project, "proposal:changed")
        return {"project": project, "results": results}
    return proposal_apply_all(project, only_passing=False)


@capability("worktree.discard_change")
def worktree_discard(project: str, change_id: str) -> dict:
    parsed = _parse_source_id(change_id)
    if parsed["source"] == "proposal":
        result = proposal_store.discard_proposal(project, parsed["proposal_id"], parsed["path"])
        _source_control_event(project, "proposal:changed")
        return {**result, "path": parsed["path"]}
    if parsed["source"] == "git":
        git_service.discard_file(
            project,
            parsed["path"],
            staged=parsed["group"] == "staged",
            untracked=parsed["group"] == "untracked",
        )
        _publish("workspace:changed", {"project": project, "paths": [parsed["path"]]})
        _source_control_event(project)
        return {"project": project, "path": parsed["path"]}
    return discard_change(project, change_id)


@capability("worktree.discard_many")
def worktree_discard_many(project: str, change_ids: list[str]) -> dict:
    results, errors = [], []
    for change_id in change_ids:
        try:
            results.append(worktree_discard(project, change_id))
        except Exception as exc:
            errors.append({"change_id": change_id, "error": str(exc)})
    _source_control_event(project)
    return {"discarded": results, "errors": errors, "status": _combined_status(project)}


@capability("worktree.discard_all")
def worktree_discard_all(project: str) -> dict:
    git_result = git_service.discard_all(project, include_untracked=True)
    proposal_result = proposal_store.discard_all(project)
    _publish("workspace:changed", {"project": project, "paths": []})
    _source_control_event(project)
    return {"project": project, "git": git_result, "proposals": proposal_result}


@capability("worktree.create_snapshot")
def worktree_snapshot(project: str, label: str | None = None, message: str | None = None) -> dict:
    return git_commit(project, message or label or "")


@capability("worktree.history")
def worktree_history(project: str) -> dict:
    legacy = get_history(project)
    return {
        "commits": git_service.get_log(project)["commits"],
        "runs": legacy.get("runs", []),
        "proposals": proposal_store.list_proposals(project, include_inactive=True)["proposals"],
        "snapshots": [],
    }


@capability("worktree.file_history")
def worktree_file_history(project: str, path: str) -> dict:
    history = git_service.get_file_history(project, path)
    return {**history, "changes": history["commits"]}


@capability("worktree.file_status")
def worktree_file_status(project: str, path: str) -> dict:
    status = _combined_status(project)
    matches = []
    for group in ("conflicts", "proposed", "changes", "untracked", "staged"):
        matches.extend({**item, "group": group} for item in status[group] if item["path"] == path)
    return {"project": project, "path": path, "changes": matches}


@capability("worktree.get_hunks")
def worktree_get_hunks(project: str, change_id: str) -> dict:
    diff = worktree_get_diff(project, change_id)
    return {"project": project, "change_id": change_id, "hunks": diff.get("hunks", [])}


@capability("worktree.stage_hunk")
def worktree_stage_hunk(project: str, change_id: str, hunk_id: str) -> dict:
    parsed = _parse_source_id(change_id)
    result = git_service.stage_hunk(project, parsed["path"], hunk_id)
    _source_control_event(project)
    return result


@capability("worktree.discard_hunk")
def worktree_discard_hunk(project: str, change_id: str, hunk_id: str) -> dict:
    parsed = _parse_source_id(change_id)
    result = git_service.discard_hunk(project, parsed["path"], hunk_id)
    _publish("workspace:changed", {"project": project, "paths": [parsed["path"]]})
    _source_control_event(project)
    return result


@capability("worktree.apply_hunk")
def worktree_apply_hunk(project: str, change_id: str, hunk_id: str) -> dict:
    raise ValueError("Proposal hunk apply is not available yet; apply the proposal file")


@capability("worktree.apply_all_hunks")
def worktree_apply_all_hunks(project: str, change_id: str) -> dict:
    return worktree_apply(project, change_id)


@capability("worktree.generate_checkpoint_message")
def worktree_generate_checkpoint_message(project: str) -> dict:
    return git_service.generate_commit_message(project)


@capability("worktree.restore_file")
def worktree_restore_file(project: str, path: str, snapshot_id: str | None = None) -> dict:
    return git_restore_file(project, path, snapshot_id or "HEAD")


@capability("worktree.compare_with_snapshot")
def worktree_compare_snapshot(project: str, path: str, snapshot_id: str | None = None) -> dict:
    ref = snapshot_id or "HEAD"
    before = git_service.run_git(project, ["show", f"{ref}:{path}"])["stdout"]
    after = safe_path(project, path).read_text(encoding="utf-8") if safe_path(project, path).is_file() else ""
    return {
        "project": project,
        "path": path,
        "snapshot_id": ref,
        "before_content": before,
        "after_content": after,
        "diff": "",
    }


@capability("worktree.restore_snapshot")
def worktree_restore_snapshot(project: str, snapshot_id: str) -> dict:
    raise ValueError("Whole-commit restore is intentionally not exposed; restore individual files")


@capability("worktree.ignore_path")
def worktree_ignore_path(project: str, path: str) -> dict:
    safe_path(project, path)
    ignore_file = safe_path(project, ".gitignore")
    existing = ignore_file.read_text(encoding="utf-8").splitlines() if ignore_file.exists() else []
    pattern = path.replace("\\", "/").strip("/")
    if safe_path(project, path).is_dir():
        pattern += "/"
    if pattern not in existing:
        existing.append(pattern)
        ignore_file.write_text("\n".join(existing).rstrip() + "\n", encoding="utf-8", newline="\n")
    _publish("workspace:changed", {"project": project, "paths": [".gitignore"]})
    _source_control_event(project)
    return {"project": project, "ignored": pattern}


@capability("worktree.timeline")
def worktree_timeline(project: str) -> dict:
    events = []
    for commit_item in git_service.get_log(project)["commits"]:
        events.append({
            "type": "commit",
            "id": commit_item["hash"],
            "label": commit_item["message"],
            "created_at": commit_item["created_at"],
        })
    for proposal in proposal_store.list_proposals(project, include_inactive=True)["proposals"]:
        events.append({
            "type": "proposal",
            "id": proposal["proposal_id"],
            "label": proposal.get("summary") or f"{proposal['status']} proposal",
            "created_at": proposal.get("updated_at") or proposal.get("created_at"),
        })
    legacy = get_timeline(project)
    events.extend(item for item in legacy["events"] if item["type"] in {"run", "model"})
    events.sort(key=lambda item: item.get("created_at") or "", reverse=True)
    return {"project": project, "events": events}




@capability("model.get_config")
def model_get_config() -> dict:
    """Return the current Colab/model connection config, with secrets masked."""
    return read_model_config(include_secret=False)


@capability("model.set_config")
def model_set_config(
    base_url: str | None = None,
    health_path: str | None = None,
    capabilities_path: str | None = None,
    chat_path: str | None = None,
    plan_path: str | None = None,
    replan_path: str | None = None,
    code_path: str | None = None,
    review_path: str | None = None,
    run_path: str | None = None,
    stream_path: str | None = None,
    run_status_path: str | None = None,
    cancel_path: str | None = None,
    timeout: int | str | None = None,
    max_iterations: int | str | None = None,
    context_mode: str | None = None,
    context_budget: int | str | None = None,
    prefer_streaming: bool | None = None,
    keep_model_loaded: bool | None = None,
    token: str | None = None,
    headers_json: str | dict | None = None,
    prompt_set_version: str | None = None,
    model_id: str | None = None,
    model_revision: str | None = None,
    input_token_price_per_million: float | str | None = None,
    output_token_price_per_million: float | str | None = None,
) -> dict:
    """Persist Colab/model connection settings used by Bob chat and model runs."""
    config = save_model_config(
        base_url=base_url,
        health_path=health_path,
        capabilities_path=capabilities_path,
        chat_path=chat_path,
        plan_path=plan_path,
        replan_path=replan_path,
        code_path=code_path,
        review_path=review_path,
        run_path=run_path,
        stream_path=stream_path,
        run_status_path=run_status_path,
        cancel_path=cancel_path,
        timeout=timeout,
        max_iterations=max_iterations,
        context_mode=context_mode,
        context_budget=context_budget,
        prefer_streaming=prefer_streaming,
        keep_model_loaded=keep_model_loaded,
        token=token,
        headers_json=headers_json,
        prompt_set_version=prompt_set_version,
        model_id=model_id,
        model_revision=model_revision,
        input_token_price_per_million=input_token_price_per_million,
        output_token_price_per_million=output_token_price_per_million,
    )
    _publish("model:config", {"project": "*", "config": config})
    return config


@capability("model.health")
def model_health() -> dict:
    """Check whether the configured Colab endpoint is reachable."""
    config = read_model_config(include_secret=True)
    if not config.get("base_url"):
        return {"configured": False, "ok": False, "message": "No Colab base URL configured."}
    try:
        payload = ColabAdapter().health()
        return {"configured": True, "ok": bool(payload.get("ok", True)), "response": payload}
    except Exception as exc:
        return {"configured": True, "ok": False, "message": str(exc)}


@capability("model.capabilities")
def model_capabilities() -> dict:
    config = read_model_config()
    if not config.get("configured"):
        return {"configured": False, "contract_version": None, "streaming": False}
    try:
        return {"configured": True, **ColabAdapter().capabilities()}
    except Exception as exc:
        return {"configured": True, "contract_version": "legacy", "streaming": False, "message": str(exc)}


@capability("model.chat")
def model_chat(project: str, message: str, active_path: str | None = None, request_id: str | None = None, actor_user_id: str | None = None) -> dict:
    if not message.strip():
        raise ValueError("Message is required")
    config = read_model_config()
    context = _limited_model_context(project, active_path, int(config.get("context_budget", 160000)))
    payload = {
        "run_id": "chat",
        "trace_id": "chat",
        "request_id": request_id,
        "actor_user_id": actor_user_id,
        "project": project,
        "user_prompt": message,
        "active_path": active_path,
        "context_mode": config.get("context_mode", "workspace"),
        **context,
    }
    def operation() -> dict:
        try:
            result = ColabAdapter().chat(payload)
            return {
                "reply": result.get("reply") or result.get("message") or result.get("response") or "",
                "provider": result.get("provider", "colab"),
                **result,
            }
        except ColabRetryError:
            raise
        except Exception:
            return assistant_chat(message, project, active_path)
    return _queued_model_call("model.chat", project, actor_user_id, request_id, operation)


@capability("context.build")
def context_build(
    project: str,
    prompt: str = "",
    active_path: str | None = None,
    forced_paths: list[str] | None = None,
    open_paths: list[str] | None = None,
    forced_files: dict[str, str] | None = None,
    plan_id: str | None = None,
    max_bytes: int | None = None,
) -> dict:
    selected_plan = plan_store.get_plan(project, plan_id)["plan"] if plan_id else None
    return build_model_context(
        project=project,
        prompt=prompt,
        active_path=active_path,
        forced_paths=forced_paths or [],
        open_paths=open_paths or [],
        forced_files=forced_files or {},
        plan=selected_plan,
        max_bytes=max_bytes or int(read_model_config().get("context_budget", 160000)),
    )


@capability("plans.list")
def plans_list(project: str, include_inactive: bool = True, run_id: str | None = None) -> dict:
    return plan_store.list_plans(project, include_inactive, run_id)


@capability("plans.get")
def plans_get(project: str, plan_id: str) -> dict:
    return plan_store.get_plan(project, plan_id)


@capability("plans.select")
def plans_select(project: str, plan_id: str) -> dict:
    result = plan_store.select_plan(project, plan_id)
    _publish("plans:changed", {"project": project})
    return result


@capability("plans.discard")
def plans_discard(project: str, plan_id: str) -> dict:
    result = plan_store.discard_plan(project, plan_id)
    _publish("plans:changed", {"project": project})
    return result


@capability("model.plan")
def model_plan(
    project: str,
    prompt: str,
    active_path: str | None = None,
    forced_paths: list[str] | None = None,
    open_paths: list[str] | None = None,
    max_bytes: int | None = None,
    forced_files: dict[str, str] | None = None,
    request_id: str | None = None,
    actor_user_id: str | None = None,
) -> dict:
    result = _queued_model_call("model.plan", project, actor_user_id, request_id, lambda: plan_stage(project, prompt, active_path, forced_paths or [], open_paths or [], max_bytes, forced_files or {}, select=True, request_id=request_id, actor_user_id=actor_user_id))
    _publish("plans:changed", {"project": project})
    return result


@capability("model.replan")
def model_replan(
    project: str,
    prompt: str = "",
    previous_plan_id: str | None = None,
    active_path: str | None = None,
    forced_paths: list[str] | None = None,
    open_paths: list[str] | None = None,
    max_bytes: int | None = None,
    forced_files: dict[str, str] | None = None,
    request_id: str | None = None,
    actor_user_id: str | None = None,
) -> dict:
    result = _queued_model_call("model.replan", project, actor_user_id, request_id, lambda: replan_stage(project, prompt, previous_plan_id, active_path, forced_paths or [], open_paths or [], max_bytes, forced_files or {}, select=True, request_id=request_id, actor_user_id=actor_user_id))
    _publish("plans:changed", {"project": project})
    return result


@capability("model.code")
def model_code(
    project: str,
    plan_id: str,
    active_path: str | None = None,
    forced_paths: list[str] | None = None,
    open_paths: list[str] | None = None,
    max_bytes: int | None = None,
    forced_files: dict[str, str] | None = None,
    request_id: str | None = None,
    actor_user_id: str | None = None,
) -> dict:
    result = _queued_model_call("model.code", project, actor_user_id, request_id, lambda: code_stage(project, plan_id, active_path, forced_paths or [], open_paths or [], max_bytes, forced_files or {}, request_id=request_id, actor_user_id=actor_user_id))
    _publish("model:run", {"project": project, "run": result.get("run"), "status": "coded"})
    return result


@capability("model.review")
def model_review(project: str, plan_id: str, code: str, files: dict, request_id: str | None = None, actor_user_id: str | None = None) -> dict:
    result = _queued_model_call("model.review", project, actor_user_id, request_id, lambda: review_stage(project, plan_id, code, files, request_id=request_id, actor_user_id=actor_user_id))
    _publish("proposal:changed", {"project": project})
    _publish("source-control:changed", {"project": project})
    return result


@capability("model.run_agent")
def model_run_agent(project: str, prompt: str, active_path: str | None = None, request_id: str | None = None, actor_user_id: str | None = None) -> dict:
    return _queued_model_call("model.run_agent", project, actor_user_id, request_id, lambda: run_agent_stage(project, prompt, active_path, request_id=request_id, actor_user_id=actor_user_id))


@capability("model.code_direct")
def model_code_direct(
    project: str,
    prompt: str,
    active_path: str | None = None,
    forced_paths: list[str] | None = None,
    open_paths: list[str] | None = None,
    max_bytes: int | None = None,
    forced_files: dict[str, str] | None = None,
    request_id: str | None = None,
    actor_user_id: str | None = None,
) -> dict:
    """Queue a direct coder request and require reviewer completion before returning."""
    result = _queued_model_call(
        "model.code_direct",
        project,
        actor_user_id,
        request_id,
        lambda: direct_code_review_stage(project, prompt, active_path, forced_paths or [], open_paths or [], max_bytes, forced_files or {}, request_id=request_id, actor_user_id=actor_user_id),
    )
    _publish("proposal:changed", {"project": project})
    _publish("source-control:changed", {"project": project})
    return result


@capability("model.queue_status")
def model_queue_status(actor_user_id: str | None = None) -> dict:
    """Return the caller's place in the shared single-lane model queue."""
    return MODEL_QUEUE.snapshot(actor_user_id)


@capability("model.run_status")
def model_status(project: str, run_id: str) -> dict:
    return model_run_status(project, run_id)
