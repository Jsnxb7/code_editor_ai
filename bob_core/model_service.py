"""Persisted asynchronous planner/agent run coordinator."""

from __future__ import annotations

import threading
from typing import Any, Callable

from bob_core.colab_adapter import ColabAdapter
from bob_core.file_manager import list_files, read_file, scan_tree
from bob_core.json_worktree import (
    create_run,
    get_run,
    record_model_proposal,
    record_model_stage,
    update_run,
)

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
    paths = list_files(project)
    files = {}
    preferred = [active_path] if active_path and active_path in paths else []
    for path in preferred + [path for path in paths if path not in preferred]:
        try:
            content = read_file(project, path)["content"]
        except Exception:
            continue
        if sum(len(value) for value in files.values()) + len(content) > 500_000:
            break
        files[path] = content
    return {"workspace_tree": scan_tree(project), "files": files}


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

        result = adapter.run_agent(payload)
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
        proposals = record_model_proposal(
            project,
            run_id,
            result["files"],
            result["final_status"],
        )
        if proposals:
            _emit_worktree_changed(project)
        record = update_run(
            project,
            run_id,
            status="completed",
            plan=plan,
            review=result.get("review", ""),
            final_status=result["final_status"],
            provider=result.get("provider", "colab"),
            linked_changes=[item["change_id"] for item in proposals],
            linked_files=[item["path"] for item in proposals],
        )
        _emit(project, run_id, "completed", run=record, proposals=proposals)
    except Exception as exc:
        record = update_run(project, run_id, status="failed", final_status="FAIL", error=str(exc))
        _emit(project, run_id, "failed", run=record, error=str(exc))


def model_run_status(project: str, run_id: str) -> dict:
    return get_run(project, run_id)
