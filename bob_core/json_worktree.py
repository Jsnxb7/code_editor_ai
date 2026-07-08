"""JSON-backed source control for Bob IDE projects."""

from __future__ import annotations

import difflib
import hashlib
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from bob_core.file_manager import is_allowed_text_file, safe_path
from bob_core.json_store import load_json, project_lock, save_json_atomic
from config import IGNORED_DIRS

SCHEMA_VERSION = "0.1"
ACTIVE_STATUSES = {"proposed", "unstaged", "staged", "conflict"}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _meta(project: str) -> Path:
    return safe_path(project) / ".bob"


def _hash(content: str | None) -> str:
    return hashlib.sha256((content or "").encode("utf-8")).hexdigest()


def _project_files(project: str) -> dict[str, str]:
    root = safe_path(project)
    files: dict[str, str] = {}
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(root)
        if any(part.startswith(".") or part in IGNORED_DIRS for part in rel.parts[:-1]):
            continue
        if path.name.startswith(".") and path.name not in {".env", ".gitignore"}:
            continue
        if not is_allowed_text_file(path):
            continue
        try:
            files[rel.as_posix()] = path.read_text(encoding="utf-8")
        except (OSError, UnicodeError):
            continue
    return files


def _default_index(project: str) -> dict:
    return {
        "schema_version": SCHEMA_VERSION,
        "project": project,
        "next_run_index": 1,
        "next_change_index": 1,
        "next_snapshot_index": 1,
        "next_patch_index": 1,
        "next_model_run_index": 1,
        "updated_at": _now(),
    }


def _read(project: str, name: str, key: str) -> dict:
    return load_json(
        _meta(project) / name,
        {"schema_version": SCHEMA_VERSION, "project": project, key: []},
    )


def _write(project: str, name: str, data: dict) -> None:
    save_json_atomic(_meta(project) / name, data)


def _next_id(project: str, counter: str, prefix: str) -> tuple[int, str]:
    path = _meta(project) / "index.json"
    data = load_json(path, _default_index(project))
    index = int(data[counter])
    data[counter] = index + 1
    data["updated_at"] = _now()
    save_json_atomic(path, data)
    return index, f"{prefix}_{index:06d}"


def _snapshot_file(project: str, snapshot_id: str) -> Path:
    return _meta(project) / "snapshots" / f"{snapshot_id}.json"


def _latest_snapshot(project: str) -> tuple[dict, dict[str, str]]:
    snapshots = _read(project, "snapshots.json", "snapshots")["snapshots"]
    if not snapshots:
        raise RuntimeError("Worktree has no baseline snapshot")
    record = snapshots[-1]
    payload = load_json(_snapshot_file(project, record["snapshot_id"]), {"files": {}})
    return record, payload.get("files", {})


def _blob_path(project: str, change_id: str, side: str) -> Path:
    return _meta(project) / "change_blobs" / f"{change_id}_{side}.txt"


def _write_blob(project: str, change_id: str, side: str, content: str) -> str:
    path = _blob_path(project, change_id, side)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8", newline="\n")
    return path.relative_to(safe_path(project)).as_posix()


def _read_blob(project: str, change: dict, side: str) -> str:
    rel = change.get(f"{side}_blob")
    if not rel:
        return ""
    path = safe_path(project, rel)
    return path.read_text(encoding="utf-8") if path.exists() else ""


def _action(before: str | None, after: str | None) -> str:
    if before is None and after is not None:
        return "add"
    if before is not None and after is None:
        return "delete"
    return "modify"


def _diff(path: str, before: str | None, after: str | None) -> str:
    return "".join(
        difflib.unified_diff(
            (before or "").splitlines(keepends=True),
            (after or "").splitlines(keepends=True),
            fromfile=f"a/{path}",
            tofile=f"b/{path}",
        )
    )


def _hunks(diff_text: str) -> list[dict[str, Any]]:
    hunks = []
    current: dict[str, Any] | None = None
    for line in diff_text.splitlines():
        if line.startswith("@@"):
            if current:
                hunks.append(current)
            parts = line.split("@@")[1].strip().split(" ")
            old_part = parts[0].lstrip("-")
            new_part = parts[1].lstrip("+") if len(parts) > 1 else "0,0"
            old_start, _, old_lines = old_part.partition(",")
            new_start, _, new_lines = new_part.partition(",")
            current = {
                "hunk_id": f"hunk_{len(hunks) + 1:06d}",
                "status": "pending",
                "old_start": int(old_start or 0),
                "old_lines": int(old_lines or 1),
                "new_start": int(new_start or 0),
                "new_lines": int(new_lines or 1),
                "diff": line + "\n",
            }
        elif current:
            current["diff"] += line + "\n"
    if current:
        hunks.append(current)
    return hunks


def _estimate_risk(path: str, action: str, review_status: str) -> str:
    lower = path.lower()
    critical = (
        "package.json", "requirements.txt", "pyproject.toml", "routes/",
        "auth", "security", ".env", "config.py", "mcp_server.py",
    )
    if review_status.upper() == "FAIL" or action == "delete":
        return "high"
    if any(part in lower for part in critical):
        return "medium"
    return "low"


def _save_patch(project: str, change_id: str, path: str, before: str | None, after: str | None) -> str:
    _, patch_id = _next_id(project, "next_patch_index", "patch")
    patch_path = _meta(project) / "patches" / f"{patch_id}.patch"
    patch_path.parent.mkdir(parents=True, exist_ok=True)
    patch_path.write_text(_diff(path, before, after), encoding="utf-8", newline="\n")
    return patch_path.relative_to(safe_path(project)).as_posix()


def init_worktree(project: str) -> dict:
    with project_lock(project):
        meta = _meta(project)
        meta.mkdir(parents=True, exist_ok=True)
        index_path = meta / "index.json"
        if not index_path.exists():
            save_json_atomic(index_path, _default_index(project))
        for name, key in (
            ("changes.json", "changes"),
            ("staged.json", "staged"),
            ("snapshots.json", "snapshots"),
            ("runs.json", "runs"),
            ("model_runs.json", "model_runs"),
        ):
            path = meta / name
            if not path.exists():
                _write(project, name, {"schema_version": SCHEMA_VERSION, "project": project, key: []})
        snapshots = _read(project, "snapshots.json", "snapshots")
        if not snapshots["snapshots"]:
            _create_snapshot_record(project, "Initial baseline", _project_files(project))
        return {"initialized": True, "project": project}


def _create_snapshot_record(project: str, label: str, files: dict[str, str]) -> dict:
    index, snapshot_id = _next_id(project, "next_snapshot_index", "snapshot")
    created_at = _now()
    payload = {
        "schema_version": SCHEMA_VERSION,
        "project": project,
        "snapshot_id": snapshot_id,
        "created_at": created_at,
        "files": files,
    }
    save_json_atomic(_snapshot_file(project, snapshot_id), payload)
    record = {
        "index": index,
        "snapshot_id": snapshot_id,
        "label": label,
        "created_at": created_at,
        "files": {
            path: {"hash": _hash(content), "size": len(content.encode("utf-8"))}
            for path, content in files.items()
        },
    }
    data = _read(project, "snapshots.json", "snapshots")
    data["snapshots"].append(record)
    _write(project, "snapshots.json", data)
    return record


def _active_change(changes: list[dict], path: str, source: str | None = None) -> dict | None:
    for change in reversed(changes):
        if change["path"] == path and change["status"] in ACTIVE_STATUSES:
            if source is None or change["source"] == source:
                return change
    return None


def record_manual_change(project: str, path: str) -> dict | None:
    with project_lock(project):
        init_worktree(project)
        _, baseline = _latest_snapshot(project)
        target = safe_path(project, path)
        current = target.read_text(encoding="utf-8") if target.is_file() else None
        before = baseline.get(path)
        diff_text = _diff(path, before, current)
        data = _read(project, "changes.json", "changes")
        existing = _active_change(data["changes"], path)
        if before == current:
            if existing and existing["source"] != "bob_model":
                existing["status"] = "discarded"
                existing["updated_at"] = _now()
                _write(project, "changes.json", data)
            return None
        if existing and existing["source"] != "bob_model":
            change = existing
            if change["status"] == "staged" and change.get("after_hash") == _hash(current):
                return change
            if change["status"] == "staged":
                staged = _read(project, "staged.json", "staged")
                staged["staged"] = [
                    item for item in staged["staged"]
                    if item["change_id"] != change["change_id"]
                ]
                _write(project, "staged.json", staged)
            change["action"] = _action(before, current)
            change["after_hash"] = _hash(current)
            change["after_size"] = len((current or "").encode("utf-8"))
            change["after_blob"] = _write_blob(project, change["change_id"], "after", current or "")
            change["patch_path"] = _save_patch(project, change["change_id"], path, before, current)
            change["hunks"] = _hunks(diff_text)
            change["status"] = "unstaged"
            change["updated_at"] = _now()
        else:
            index, change_id = _next_id(project, "next_change_index", "change")
            change = {
                "index": index,
                "change_id": change_id,
                "run_id": None,
                "source": "manual",
                "path": path,
                "action": _action(before, current),
                "status": "unstaged",
                "before_hash": _hash(before),
                "after_hash": _hash(current),
                "before_size": len((before or "").encode("utf-8")),
                "after_size": len((current or "").encode("utf-8")),
                "before_blob": _write_blob(project, change_id, "before", before or ""),
                "after_blob": _write_blob(project, change_id, "after", current or ""),
                "hunks": _hunks(diff_text),
                "created_at": _now(),
                "updated_at": _now(),
            }
            change["patch_path"] = _save_patch(project, change_id, path, before, current)
            data["changes"].append(change)
        _write(project, "changes.json", data)
        return change


def record_rename(project: str, old_path: str, new_path: str) -> list[dict]:
    with project_lock(project):
        return [
            item
            for item in (record_manual_change(project, old_path), record_manual_change(project, new_path))
            if item
        ]


def detect_manual_changes(project: str) -> dict:
    with project_lock(project):
        init_worktree(project)
        parent_snapshot, baseline = _latest_snapshot(project)
        current = _project_files(project)
        for path in sorted(set(baseline) | set(current)):
            record_manual_change(project, path)
        return get_status(project)


def record_model_proposal(
    project: str,
    run_id: str,
    files: dict[str, str | None],
    review_status: str = "PASS",
) -> list[dict]:
    with project_lock(project):
        init_worktree(project)
        data = _read(project, "changes.json", "changes")
        proposals = []
        for path, after in files.items():
            target = safe_path(project, path)
            before = target.read_text(encoding="utf-8") if target.is_file() else None
            if before == after:
                continue
            diff_text = _diff(path, before, after)
            index, change_id = _next_id(project, "next_change_index", "change")
            review = review_status.upper()
            change = {
                "index": index,
                "change_id": change_id,
                "run_id": run_id,
                "source": "bob_model",
                "path": path,
                "action": _action(before, after),
                "status": "proposed",
                "review_status": review,
                "risk": _estimate_risk(path, _action(before, after), review),
                "base_hash": _hash(before),
                "before_hash": _hash(before),
                "after_hash": _hash(after),
                "before_size": len((before or "").encode("utf-8")),
                "after_size": len((after or "").encode("utf-8")),
                "before_blob": _write_blob(project, change_id, "before", before or ""),
                "after_blob": _write_blob(project, change_id, "after", after or ""),
                "hunks": _hunks(diff_text),
                "created_at": _now(),
                "updated_at": _now(),
            }
            change["patch_path"] = _save_patch(project, change_id, path, before, after)
            data["changes"].append(change)
            proposals.append(change)
        _write(project, "changes.json", data)
        return proposals


def _find_change(project: str, change_id: str) -> tuple[dict, dict]:
    data = _read(project, "changes.json", "changes")
    change = next((item for item in data["changes"] if item["change_id"] == change_id), None)
    if not change:
        raise KeyError(f"Change not found: {change_id}")
    return data, change


def get_status(project: str) -> dict:
    with project_lock(project):
        init_worktree(project)
        changes = [
            item for item in _read(project, "changes.json", "changes")["changes"]
            if item["status"] in ACTIVE_STATUSES
        ]
        grouped = {
            "proposed": [c for c in changes if c["status"] == "proposed"],
            "changes": [c for c in changes if c["status"] == "unstaged"],
            "staged": [c for c in changes if c["status"] == "staged"],
            "conflicts": [c for c in changes if c["status"] == "conflict"],
        }
        summary = {key: len(value) for key, value in grouped.items()}
        state = "clean" if not changes else "conflict" if grouped["conflicts"] else "dirty"
        snapshot, _ = _latest_snapshot(project)
        return {
            "project": project,
            "state": state,
            "summary": summary,
            "active_snapshot": snapshot.get("snapshot_id"),
            "active_worktree": "main",
            **grouped,
        }


def get_diff(project: str, change_id: str) -> dict:
    with project_lock(project):
        init_worktree(project)
        _, change = _find_change(project, change_id)
        before = _read_blob(project, change, "before")
        after = _read_blob(project, change, "after")
        return {**change, "before_content": before, "after_content": after, "diff": _diff(change["path"], before, after)}


def stage_change(project: str, change_id: str) -> dict:
    with project_lock(project):
        data, change = _find_change(project, change_id)
        if change["status"] != "unstaged":
            raise ValueError("Only unstaged changes can be staged")
        staged = _read(project, "staged.json", "staged")
        staged["staged"] = [item for item in staged["staged"] if item["change_id"] != change_id]
        staged["staged"].append({
            "change_id": change_id,
            "path": change["path"],
            "action": change["action"],
            "after_blob": change["after_blob"],
            "after_hash": change["after_hash"],
            "staged_at": _now(),
        })
        change["status"] = "staged"
        change["updated_at"] = _now()
        _write(project, "staged.json", staged)
        _write(project, "changes.json", data)
        return change


def unstage_change(project: str, change_id: str) -> dict:
    with project_lock(project):
        data, change = _find_change(project, change_id)
        if change["status"] != "staged":
            raise ValueError("Only staged changes can be unstaged")
        staged = _read(project, "staged.json", "staged")
        staged["staged"] = [item for item in staged["staged"] if item["change_id"] != change_id]
        change["status"] = "unstaged"
        change["updated_at"] = _now()
        _write(project, "staged.json", staged)
        _write(project, "changes.json", data)
        return change


def stage_all(project: str) -> dict:
    for change in list(get_status(project)["changes"]):
        stage_change(project, change["change_id"])
    return get_status(project)


def unstage_all(project: str) -> dict:
    for change in list(get_status(project)["staged"]):
        unstage_change(project, change["change_id"])
    return get_status(project)


def _write_change_content(project: str, change: dict, content: str | None) -> None:
    target = safe_path(project, change["path"])
    if change["action"] == "delete" or content is None:
        if target.exists() and target.is_file():
            target.unlink()
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8", newline="\n")


def apply_change(project: str, change_id: str, override: bool = False) -> dict:
    with project_lock(project):
        data, change = _find_change(project, change_id)
        if change["status"] not in {"proposed", "conflict"}:
            raise ValueError("Only proposed or conflicted changes can be applied")
        if change.get("review_status") == "FAIL" and not override:
            raise ValueError("Reviewer failed this proposal; explicit override is required")
        target = safe_path(project, change["path"])
        current = target.read_text(encoding="utf-8") if target.is_file() else None
        if _hash(current) != change["base_hash"] and not override:
            change["status"] = "conflict"
            change["updated_at"] = _now()
            _write(project, "changes.json", data)
            raise ValueError("File changed since this proposal was created")
        after = _read_blob(project, change, "after")
        _write_change_content(project, change, None if change["action"] == "delete" else after)
        change["status"] = "unstaged"
        change["override_applied"] = bool(override)
        change["updated_at"] = _now()
        _write(project, "changes.json", data)
        return change


def apply_all(project: str, override: bool = False) -> dict:
    results, errors = [], []
    for change in list(get_status(project)["proposed"] + get_status(project)["conflicts"]):
        try:
            results.append(apply_change(project, change["change_id"], override))
        except Exception as exc:
            errors.append({"change_id": change["change_id"], "error": str(exc)})
    return {"applied": results, "errors": errors, "status": get_status(project)}


def discard_change(project: str, change_id: str) -> dict:
    with project_lock(project):
        data, change = _find_change(project, change_id)
        if change["status"] == "staged":
            unstage_change(project, change_id)
            data, change = _find_change(project, change_id)
        if change["status"] == "unstaged" or (
            change["status"] == "conflict" and change["source"] != "bob_model"
        ):
            before = _read_blob(project, change, "before")
            _write_change_content(project, change, None if change["action"] == "add" else before)
        change["status"] = "discarded"
        change["updated_at"] = _now()
        staged = _read(project, "staged.json", "staged")
        staged["staged"] = [item for item in staged["staged"] if item["change_id"] != change_id]
        _write(project, "staged.json", staged)
        _write(project, "changes.json", data)
        return change


def discard_all(project: str) -> dict:
    status = get_status(project)
    for group in ("proposed", "changes", "staged", "conflicts"):
        for change in list(status[group]):
            discard_change(project, change["change_id"])
    return get_status(project)


def create_snapshot(project: str, label: str | None = None, message: str | None = None) -> dict:
    with project_lock(project):
        init_worktree(project)
        _, baseline = _latest_snapshot(project)
        next_baseline = dict(baseline)
        staged = _read(project, "staged.json", "staged")
        changes_data = _read(project, "changes.json", "changes")
        for item in staged["staged"]:
            if item["action"] == "delete":
                next_baseline.pop(item["path"], None)
            else:
                next_baseline[item["path"]] = safe_path(project, item["after_blob"]).read_text(encoding="utf-8")
        staged_ids = {item["change_id"] for item in staged["staged"]}
        record = _create_snapshot_record(project, message or label or "Checkpoint", next_baseline)
        record["message"] = message or label or "Checkpoint"
        record["type"] = "manual_checkpoint"
        record["parent_snapshot"] = parent_snapshot.get("snapshot_id")
        record["staged_changes"] = sorted(staged_ids)
        record["validation"] = {}
        snapshots_data = _read(project, "snapshots.json", "snapshots")
        snapshots_data["snapshots"][-1] = record
        _write(project, "snapshots.json", snapshots_data)
        for change in changes_data["changes"]:
            if change["change_id"] in staged_ids:
                change["status"] = "checkpointed"
                change["snapshot_id"] = record["snapshot_id"]
                change["updated_at"] = _now()
        staged["staged"] = []
        _write(project, "changes.json", changes_data)
        _write(project, "staged.json", staged)
        detect_manual_changes(project)
        return record


def get_history(project: str) -> dict:
    with project_lock(project):
        init_worktree(project)
        return {
            "snapshots": _read(project, "snapshots.json", "snapshots")["snapshots"],
            "runs": _read(project, "runs.json", "runs")["runs"],
        }


def get_file_history(project: str, path: str) -> dict:
    with project_lock(project):
        init_worktree(project)
        changes = [
            item for item in _read(project, "changes.json", "changes")["changes"]
            if item["path"] == path
        ]
        return {"project": project, "path": path, "changes": changes}


def create_run(project: str, prompt: str, mode: str) -> dict:
    with project_lock(project):
        init_worktree(project)
        index, run_id = _next_id(project, "next_run_index", "run")
        record = {
            "index": index,
            "run_id": run_id,
            "user_prompt": prompt,
            "mode": mode,
            "status": "queued",
            "created_at": _now(),
            "updated_at": _now(),
            "linked_changes": [],
            "linked_files": [],
        }
        data = _read(project, "runs.json", "runs")
        data["runs"].append(record)
        _write(project, "runs.json", data)
        return record


def update_run(project: str, run_id: str, **updates: Any) -> dict:
    with project_lock(project):
        data = _read(project, "runs.json", "runs")
        record = next((item for item in data["runs"] if item["run_id"] == run_id), None)
        if not record:
            raise KeyError(f"Run not found: {run_id}")
        record.update(updates)
        record["updated_at"] = _now()
        _write(project, "runs.json", data)
        return record


def get_run(project: str, run_id: str) -> dict:
    with project_lock(project):
        init_worktree(project)
        runs = _read(project, "runs.json", "runs")["runs"]
        record = next((item for item in runs if item["run_id"] == run_id), None)
        if not record:
            raise KeyError(f"Run not found: {run_id}")
        return record


def record_model_stage(project: str, run_id: str, stage: str, output: Any) -> dict:
    with project_lock(project):
        index, record_id = _next_id(project, "next_model_run_index", "model_run")
        record = {
            "index": index,
            "model_run_id": record_id,
            "run_id": run_id,
            "stage": stage,
            "output": output,
            "created_at": _now(),
        }
        data = _read(project, "model_runs.json", "model_runs")
        data["model_runs"].append(record)
        _write(project, "model_runs.json", data)
        return record
