"""Append-only plan store for Bob's staged plan -> code -> review workflow."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from bob_core.file_manager import safe_path
from bob_core.json_store import load_json, project_lock, save_json_atomic

ACTIVE_PLAN_STATES = {"ready", "selected", "replanned", "sent_to_coder"}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _bob(project: str) -> Path:
    path = safe_path(project, ".bob")
    path.mkdir(parents=True, exist_ok=True)
    return path


def _path(project: str) -> Path:
    return _bob(project) / "plans.json"


def _load(project: str) -> dict[str, Any]:
    return load_json(_path(project), {"schema_version": "1.0", "next_index": 1, "plans": []})


def _save(project: str, data: dict[str, Any]) -> None:
    save_json_atomic(_path(project), data)


def create_plan(
    project: str,
    run_id: str,
    prompt: str,
    plan: dict[str, Any],
    *,
    context_used: dict[str, Any] | None = None,
    replanned_from: str | None = None,
    selected: bool = False,
) -> dict[str, Any]:
    """Append a model plan as a selectable artifact."""
    with project_lock(project):
        data = _load(project)
        index = int(data.get("next_index", 1))
        plan_id = f"plan_{index:06d}"
        if selected:
            for item in data["plans"]:
                item["selected"] = False
                if item.get("status") == "selected":
                    item["status"] = "ready"
        record = {
            "index": index,
            "plan_id": plan_id,
            "run_id": run_id,
            "prompt": prompt,
            "status": "selected" if selected else "ready",
            "selected": bool(selected),
            "replanned_from": replanned_from,
            "created_at": _now(),
            "updated_at": _now(),
            "context_used": context_used or {},
            "plan": plan or {},
        }
        data["plans"].append(record)
        data["next_index"] = index + 1
        _save(project, data)
        return record


def list_plans(project: str, include_inactive: bool = True, run_id: str | None = None) -> dict[str, Any]:
    plans = list(_load(project).get("plans", []))
    if run_id:
        plans = [item for item in plans if item.get("run_id") == run_id]
    if not include_inactive:
        plans = [item for item in plans if item.get("status") in ACTIVE_PLAN_STATES]
    plans.sort(key=lambda item: int(item.get("index", 0)), reverse=True)
    selected = next((item for item in plans if item.get("selected")), None)
    return {"project": project, "selected_plan_id": selected.get("plan_id") if selected else None, "plans": plans}


def get_plan(project: str, plan_id: str) -> dict[str, Any]:
    plan = next((item for item in _load(project).get("plans", []) if item.get("plan_id") == plan_id), None)
    if not plan:
        raise KeyError(f"Plan not found: {plan_id}")
    return plan


def select_plan(project: str, plan_id: str) -> dict[str, Any]:
    with project_lock(project):
        data = _load(project)
        selected = None
        for item in data["plans"]:
            item["selected"] = item.get("plan_id") == plan_id
            if item["selected"]:
                item["status"] = "selected"
                item["updated_at"] = _now()
                selected = item
            elif item.get("status") == "selected":
                item["status"] = "ready"
                item["updated_at"] = _now()
        if not selected:
            raise KeyError(f"Plan not found: {plan_id}")
        _save(project, data)
        return selected


def mark_plan_status(project: str, plan_id: str, status: str, **updates: Any) -> dict[str, Any]:
    with project_lock(project):
        data = _load(project)
        plan = next((item for item in data["plans"] if item.get("plan_id") == plan_id), None)
        if not plan:
            raise KeyError(f"Plan not found: {plan_id}")
        plan.update(updates)
        plan["status"] = status
        plan["updated_at"] = _now()
        _save(project, data)
        return plan


def discard_plan(project: str, plan_id: str) -> dict[str, Any]:
    with project_lock(project):
        data = _load(project)
        plan = next((item for item in data["plans"] if item.get("plan_id") == plan_id), None)
        if not plan:
            raise KeyError(f"Plan not found: {plan_id}")
        plan["status"] = "discarded"
        plan["selected"] = False
        plan["updated_at"] = _now()
        _save(project, data)
        return plan
