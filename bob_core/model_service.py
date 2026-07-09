"""Persisted asynchronous planner/agent run coordinator."""

from __future__ import annotations

import threading
from typing import Any, Callable

from bob_core.colab_adapter import ColabAdapter
from bob_core.file_manager import list_files, read_file, scan_tree
from bob_core.json_worktree import (
    create_run,
    get_run,
    record_model_stage,
    update_run,
)
from bob_core.proposal_store import create_proposal
from bob_core.model_config import read_model_config
from bob_core import git_service

_publisher: Callable[[str, dict[str, Any]], None] | None = None


def set_model_event_publisher(publisher: Callable[[str, dict[str, Any]], None] | None) -> None:
    global _publisher
    _publisher = publisher


def _emit(project: str, run_id: str, status: str, **extra: Any) -> None:
    payload = {"project": project, "run_id": run_id, "status": status, **extra}
    if _publisher:
        _publisher("model:run", payload)


def _emit_worktree_changed(project: str) -> None:
    if _publisher:
        _publisher("worktree:changed", {"project": project})


def _context(project: str, active_path: str | None) -> dict:
    config = read_model_config()
    paths = list_files(project)
    files = {}
    preferred = [active_path] if active_path and active_path in paths else []
    ordered = preferred if config.get("context_mode") == "active" else preferred + [path for path in paths if path not in preferred]
    budget = int(config.get("context_budget", 160000))
    for path in ordered:
        try:
            content = read_file(project, path)["content"]
        except Exception:
            continue
        if sum(len(value) for value in files.values()) + len(content) > budget:
            break
        files[path] = content
    git_context = {}
    if git_service.is_git_repo(project)["is_repo"]:
        status = git_service.get_status(project)
        git_context = {"branch": status.get("branch"), "head": status.get("head")}
    return {
        "workspace_tree": scan_tree(project),
        "files": files,
        "context_mode": config.get("context_mode", "workspace"),
        "context_budget": budget,
        "max_iterations": int(config.get("max_iterations", 5)),
        "keep_model_loaded": bool(config.get("keep_model_loaded", True)),
        "git": git_context,
    }


def start_model_run(
    project: str,
    prompt: str,
    mode: str,
    active_path: str | None = None,
) -> dict:
    if mode not in {"plan", "agent"}:
        raise ValueError("Mode must be plan or agent")
    run = create_run(project, prompt, mode)
    thread = threading.Thread(
        target=_execute,
        args=(project, run["run_id"], prompt, mode, active_path),
        name=f"bob-{run['run_id']}",
        daemon=True,
    )
    thread.start()
    return run


def _execute(project: str, run_id: str, prompt: str, mode: str, active_path: str | None) -> None:
    try:
        _emit(project, run_id, "planning")
        update_run(project, run_id, status="planning")
        payload = {
            "run_id": run_id,
            "project": project,
            "user_prompt": prompt,
            "active_path": active_path,
            **_context(project, active_path),
        }
        adapter = ColabAdapter()
        if mode == "plan":
            plan = adapter.plan(payload)
            record_model_stage(project, run_id, "planner", plan)
            record = update_run(project, run_id, status="completed", plan=plan, final_status="PLAN")
            _emit(project, run_id, "completed", run=record)
            return

        def on_stream_event(event: dict) -> None:
            status = event.get("status")
            if status in {"queued", "running", "planning", "context", "coding", "reviewing"}:
                update_run(project, run_id, status=status)
                record_model_stage(project, run_id, status, event)
                _emit(project, run_id, status, event=event)

        result = adapter.run_agent_stream(payload, on_stream_event)
        plan = result["plan"]
        record_model_stage(project, run_id, "planner", plan)
        _emit(project, run_id, "coding", plan=plan)
        update_run(project, run_id, status="coding", plan=plan)
        record_model_stage(project, run_id, "coder", {"code": result.get("code", ""), "files": list(result["files"])})
        _emit(project, run_id, "reviewing", files=list(result["files"]))
        update_run(project, run_id, status="reviewing")
        record_model_stage(project, run_id, "reviewer", {
            "review": result.get("review", ""),
            "final_status": result["final_status"],
        })
        proposal = create_proposal(
            project,
            run_id,
            result["files"],
            result["final_status"],
            summary=plan.get("summary", ""),
            review=result.get("review", ""),
        )
        proposal_files = proposal.get("files", [])
        if proposal_files:
            _emit_worktree_changed(project)
        record = update_run(
            project,
            run_id,
            status="completed",
            plan=plan,
            review=result.get("review", ""),
            final_status=result["final_status"],
            provider=result.get("provider", "colab"),
            linked_proposals=[proposal["proposal_id"]],
            linked_changes=[f"proposal:{proposal['proposal_id']}:{item['path']}" for item in proposal_files],
            linked_files=[item["path"] for item in proposal_files],
        )
        _emit(project, run_id, "completed", run=record, proposals=[proposal])
    except Exception as exc:
        record = update_run(project, run_id, status="failed", final_status="FAIL", error=str(exc))
        _emit(project, run_id, "failed", run=record, error=str(exc))


def model_run_status(project: str, run_id: str) -> dict:
    return get_run(project, run_id)
