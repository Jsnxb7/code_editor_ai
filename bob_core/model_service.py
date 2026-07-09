"""Persisted staged Bob model coordinator.

Supports both the older queued Plan/Run flow and the newer interactive staged
flow: plan -> select/replan -> code -> review -> proposal cache.
"""

from __future__ import annotations

import threading
from typing import Any, Callable

from bob_core.colab_adapter import ColabAdapter
from bob_core.context_builder import build_context
from bob_core.json_worktree import create_run, get_run, record_model_stage, update_run
from bob_core.plan_store import create_plan, get_plan, mark_plan_status, select_plan
from bob_core.proposal_store import create_proposal
from bob_core.model_config import read_model_config

_publisher: Callable[[str, dict[str, Any]], None] | None = None


def set_model_event_publisher(publisher: Callable[[str, dict[str, Any]], None] | None) -> None:
    global _publisher
    _publisher = publisher


def _emit(project: str, run_id: str, status: str, **extra: Any) -> None:
    payload = {"project": project, "run_id": run_id, "status": status, **extra}
    if _publisher:
        _publisher("model:run", payload)


def _emit_changed(project: str, *events: str) -> None:
    if not _publisher:
        return
    for event in events or ("model:run",):
        _publisher(event, {"project": project})


def _cfg_budget() -> int:
    try:
        return int(read_model_config().get("context_budget", 160000))
    except Exception:
        return 160000


def _build_payload(
    project: str,
    prompt: str,
    active_path: str | None = None,
    forced_paths: list[str] | None = None,
    open_paths: list[str] | None = None,
    forced_files: dict[str, str] | None = None,
    plan: dict[str, Any] | None = None,
    max_bytes: int | None = None,
) -> dict[str, Any]:
    context = build_context(
        project=project,
        prompt=prompt,
        active_path=active_path,
        forced_paths=forced_paths or [],
        open_paths=open_paths or [],
        forced_files=forced_files or {},
        plan=plan,
        max_bytes=max_bytes or _cfg_budget(),
    )
    return {
        "project": project,
        "user_prompt": prompt,
        "active_path": active_path,
        **context,
    }


def plan_stage(
    project: str,
    prompt: str,
    active_path: str | None = None,
    forced_paths: list[str] | None = None,
    open_paths: list[str] | None = None,
    max_bytes: int | None = None,
    forced_files: dict[str, str] | None = None,
    select: bool = True,
) -> dict[str, Any]:
    """Run planner synchronously and append a selectable plan artifact."""
    run = create_run(project, prompt, "plan")
    run_id = run["run_id"]
    update_run(project, run_id, status="planning")
    payload = _build_payload(project, prompt, active_path, forced_paths, open_paths, forced_files, None, max_bytes)
    payload["run_id"] = run_id
    adapter = ColabAdapter()
    plan = adapter.plan(payload)
    stage = record_model_stage(project, run_id, "planner", {"plan": plan, "context_used": {
        "files": list(payload.get("files", {})),
        "forced_files": list(payload.get("forced_files", {})),
        "total_bytes": payload.get("total_bytes"),
    }})
    plan_record = create_plan(
        project,
        run_id,
        prompt,
        plan,
        context_used={
            "files": list(payload.get("files", {})),
            "forced_files": list(payload.get("forced_files", {})),
            "selected_paths": payload.get("selected_paths", []),
            "skipped_paths": payload.get("skipped_paths", []),
            "total_bytes": payload.get("total_bytes"),
        },
        selected=select,
    )
    update_run(project, run_id, status="completed", final_status="PLAN", plan=plan, plan_id=plan_record["plan_id"])
    _emit(project, run_id, "completed", run=get_run(project, run_id), plan_record=plan_record)
    _emit_changed(project, "plans:changed")
    return {"run": get_run(project, run_id), "plan_record": plan_record, "model_stage": stage}


def replan_stage(
    project: str,
    prompt: str,
    previous_plan_id: str | None = None,
    active_path: str | None = None,
    forced_paths: list[str] | None = None,
    open_paths: list[str] | None = None,
    max_bytes: int | None = None,
    forced_files: dict[str, str] | None = None,
    select: bool = True,
) -> dict[str, Any]:
    previous = get_plan(project, previous_plan_id) if previous_plan_id else None
    run = create_run(project, prompt or previous.get("prompt", ""), "replan")
    run_id = run["run_id"]
    base_plan = previous.get("plan") if previous else None
    payload = _build_payload(project, prompt or previous.get("prompt", ""), active_path, forced_paths, open_paths, forced_files, base_plan, max_bytes)
    payload.update({"run_id": run_id, "previous_plan_id": previous_plan_id, "previous_plan": base_plan})
    update_run(project, run_id, status="planning")
    body = ColabAdapter().replan(payload)
    plan = body.get("plan") or {}
    stage = record_model_stage(project, run_id, "planner", {"plan": plan, "replanned_from": previous_plan_id, "context_used": {
        "files": list(payload.get("files", {})),
        "forced_files": list(payload.get("forced_files", {})),
        "total_bytes": payload.get("total_bytes"),
    }})
    plan_record = create_plan(
        project,
        run_id,
        prompt or previous.get("prompt", ""),
        plan,
        context_used={
            "files": list(payload.get("files", {})),
            "forced_files": list(payload.get("forced_files", {})),
            "selected_paths": payload.get("selected_paths", []),
            "skipped_paths": payload.get("skipped_paths", []),
            "total_bytes": payload.get("total_bytes"),
        },
        replanned_from=previous_plan_id,
        selected=select,
    )
    if previous_plan_id:
        mark_plan_status(project, previous_plan_id, "replanned", replanned_to=plan_record["plan_id"])
    update_run(project, run_id, status="completed", final_status="PLAN", plan=plan, plan_id=plan_record["plan_id"])
    _emit(project, run_id, "completed", run=get_run(project, run_id), plan_record=plan_record)
    _emit_changed(project, "plans:changed")
    return {"run": get_run(project, run_id), "plan_record": plan_record, "model_stage": stage}


def code_stage(
    project: str,
    plan_id: str,
    active_path: str | None = None,
    forced_paths: list[str] | None = None,
    open_paths: list[str] | None = None,
    max_bytes: int | None = None,
    forced_files: dict[str, str] | None = None,
) -> dict[str, Any]:
    plan_record = get_plan(project, plan_id)
    plan = plan_record.get("plan", {})
    prompt = plan_record.get("prompt", "")
    run_id = plan_record.get("run_id")
    payload = _build_payload(project, prompt, active_path, forced_paths, open_paths, forced_files, plan, max_bytes)
    payload.update({"run_id": run_id, "plan_id": plan_id, "selected_plan": plan, "plan": plan})
    update_run(project, run_id, status="coding", plan=plan, plan_id=plan_id)
    body = ColabAdapter().code(payload)
    code = body.get("code", "")
    files = body.get("files", {})
    stage = record_model_stage(project, run_id, "coder", {"plan_id": plan_id, "code": code, "files": files})
    mark_plan_status(project, plan_id, "sent_to_coder")
    update_run(project, run_id, status="coded", code=code, files=files, plan_id=plan_id)
    _emit(project, run_id, "coded", run=get_run(project, run_id), files=list(files))
    return {"run": get_run(project, run_id), "plan_record": get_plan(project, plan_id), "code": code, "files": files, "model_stage": stage}


def review_stage(
    project: str,
    plan_id: str,
    code: str,
    files: dict[str, str | None],
) -> dict[str, Any]:
    plan_record = get_plan(project, plan_id)
    plan = plan_record.get("plan", {})
    run_id = plan_record.get("run_id")
    payload = {"run_id": run_id, "project": project, "plan_id": plan_id, "plan": plan, "code": code, "files": files}
    update_run(project, run_id, status="reviewing")
    body = ColabAdapter().review(payload)
    review = body.get("review", "")
    final_status = body.get("final_status", "FAIL")
    record_model_stage(project, run_id, "reviewer", {"plan_id": plan_id, "review": review, "final_status": final_status})
    proposal = create_proposal(
        project,
        run_id,
        files,
        final_status,
        summary=plan.get("summary", ""),
        review=review,
    )
    update_run(
        project,
        run_id,
        status="completed",
        review=review,
        final_status=final_status,
        plan=plan,
        plan_id=plan_id,
        linked_proposals=[proposal["proposal_id"]],
        linked_changes=[f"proposal:{proposal['proposal_id']}:{item['path']}" for item in proposal.get("files", [])],
        linked_files=[item["path"] for item in proposal.get("files", [])],
    )
    _emit(project, run_id, "completed", run=get_run(project, run_id), proposals=[proposal])
    _emit_changed(project, "proposal:changed", "source-control:changed", "worktree:changed")
    return {"run": get_run(project, run_id), "review": review, "final_status": final_status, "proposal": proposal}


# ---- Compatibility queued flow ----

def start_model_run(project: str, prompt: str, mode: str, active_path: str | None = None) -> dict:
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
        if mode == "plan":
            result = plan_stage(project, prompt, active_path, select=True)
            # Keep the original queued run id in a completed state too.
            update_run(project, run_id, status="completed", final_status="PLAN", plan=result["plan_record"].get("plan"), linked_plan=result["plan_record"]["plan_id"])
            _emit(project, run_id, "completed", run=get_run(project, run_id), plan_record=result["plan_record"])
            return
        _emit(project, run_id, "running")
        context = _build_payload(project, prompt, active_path)
        context["run_id"] = run_id
        update_run(project, run_id, status="running")
        result = ColabAdapter().run_agent(context)
        plan = result.get("plan", {})
        record_model_stage(project, run_id, "planner", plan)
        plan_record = create_plan(project, run_id, prompt, plan, context_used={"files": list(context.get("files", {}))}, selected=True)
        record_model_stage(project, run_id, "coder", {"code": result.get("code", ""), "files": result.get("files", {})})
        record_model_stage(project, run_id, "reviewer", {"review": result.get("review", ""), "final_status": result.get("final_status", "FAIL")})
        proposal = create_proposal(project, run_id, result.get("files", {}), result.get("final_status", "FAIL"), summary=plan.get("summary", ""), review=result.get("review", ""))
        record = update_run(
            project,
            run_id,
            status="completed",
            plan=plan,
            plan_id=plan_record["plan_id"],
            review=result.get("review", ""),
            final_status=result.get("final_status", "FAIL"),
            provider=result.get("provider", "colab"),
            linked_proposals=[proposal["proposal_id"]],
            linked_changes=[f"proposal:{proposal['proposal_id']}:{item['path']}" for item in proposal.get("files", [])],
            linked_files=[item["path"] for item in proposal.get("files", [])],
        )
        _emit(project, run_id, "completed", run=record, proposals=[proposal])
        _emit_changed(project, "plans:changed", "proposal:changed", "source-control:changed", "worktree:changed")
    except Exception as exc:
        record = update_run(project, run_id, status="failed", final_status="FAIL", error=str(exc))
        _emit(project, run_id, "failed", run=record, error=str(exc))


def model_run_status(project: str, run_id: str) -> dict:
    return get_run(project, run_id)
