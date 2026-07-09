"""Persistent Bob proposal cache, separate from Git source-control truth."""

from __future__ import annotations

import difflib
import hashlib
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from bob_core.file_manager import safe_path
from bob_core.json_store import load_json, project_lock, save_json_atomic
from bob_core.git_service import run_git, is_git_repo


ACTIVE_STATES = {"proposed", "conflict", "failed_review"}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _bob(project: str) -> Path:
    path = safe_path(project, ".bob")
    path.mkdir(parents=True, exist_ok=True)
    return path


def _index_path(project: str) -> Path:
    return _bob(project) / "proposals.json"


def _load(project: str) -> dict:
    return load_json(_index_path(project), {"schema_version": "1.0", "next_index": 1, "proposals": []})


def _save(project: str, data: dict) -> None:
    save_json_atomic(_index_path(project), data)


def _hash(content: str | None) -> str:
    return hashlib.sha256((content or "").encode("utf-8")).hexdigest()


def _diff(path: str, before: str | None, after: str | None) -> str:
    return "".join(difflib.unified_diff(
        (before or "").splitlines(keepends=True),
        (after or "").splitlines(keepends=True),
        fromfile=f"a/{path}",
        tofile=f"b/{path}",
    ))


def _action(before: str | None, after: str | None) -> str:
    if after is None:
        return "delete"
    if before is None:
        return "add"
    return "modify"


def _risk(path: str, review: str) -> str:
    if review == "FAIL" or path.endswith((".env", ".lock", ".sql")):
        return "high"
    if path.endswith((".py", ".js", ".jsx", ".ts", ".tsx")):
        return "medium"
    return "low"


def _blob_name(path: str, side: str) -> str:
    return f"{hashlib.sha256(path.encode()).hexdigest()[:20]}.{side}"


def create_proposal(
    project: str,
    run_id: str,
    files: dict[str, str | None],
    review_status: str = "PASS",
    summary: str = "",
    review: str = "",
    before_files: dict[str, str | None] | None = None,
) -> dict:
    with project_lock(project):
        data = _load(project)
        index = int(data.get("next_index", 1))
        proposal_id = f"proposal_{index:06d}"
        folder = _bob(project) / "proposals" / proposal_id
        blobs = folder / "files"
        patches = folder / "patches"
        blobs.mkdir(parents=True, exist_ok=True)
        patches.mkdir(parents=True, exist_ok=True)
        review_status = (review_status or "FAIL").upper()
        records = []
        for path, after in files.items():
            target = safe_path(project, path)
            before = (
                before_files.get(path)
                if before_files is not None and path in before_files
                else target.read_text(encoding="utf-8") if target.is_file() else None
            )
            if before == after:
                continue
            before_name = _blob_name(path, "before")
            after_name = _blob_name(path, "after")
            (blobs / before_name).write_text(before or "", encoding="utf-8")
            (blobs / after_name).write_text(after or "", encoding="utf-8")
            patch_name = f"{hashlib.sha256(path.encode()).hexdigest()[:20]}.patch"
            patch = _diff(path, before, after)
            (patches / patch_name).write_text(patch, encoding="utf-8")
            records.append({
                "path": path,
                "action": _action(before, after),
                "before_hash": _hash(before),
                "after_hash": _hash(after),
                "before_blob": str((blobs / before_name).relative_to(safe_path(project))).replace("\\", "/"),
                "after_blob": str((blobs / after_name).relative_to(safe_path(project))).replace("\\", "/"),
                "patch_path": str((patches / patch_name).relative_to(safe_path(project))).replace("\\", "/"),
                "status": "proposed",
            })
        head = run_git(project, ["rev-parse", "HEAD"])["stdout"].strip() if is_git_repo(project)["is_repo"] else None
        proposal = {
            "index": index,
            "proposal_id": proposal_id,
            "run_id": run_id,
            "status": "failed_review" if review_status == "FAIL" else "proposed",
            "review_status": review_status,
            "summary": summary,
            "review": review,
            "risk": max((_risk(item["path"], review_status) for item in records), default="low", key={"low": 0, "medium": 1, "high": 2}.get),
            "base_git_head": head or None,
            "created_at": _now(),
            "updated_at": _now(),
            "files": records,
        }
        save_json_atomic(folder / "metadata.json", proposal)
        data["next_index"] = index + 1
        data["proposals"].append(proposal)
        _save(project, data)
        return proposal


def list_proposals(project: str, include_inactive: bool = False) -> dict:
    proposals = _load(project).get("proposals", [])
    if not include_inactive:
        proposals = [item for item in proposals if item.get("status") in ACTIVE_STATES]
    return {"project": project, "proposals": proposals}


def _find(project: str, proposal_id: str) -> tuple[dict, dict]:
    data = _load(project)
    proposal = next((item for item in data["proposals"] if item["proposal_id"] == proposal_id), None)
    if not proposal:
        raise KeyError(f"Proposal not found: {proposal_id}")
    return data, proposal


def _file(proposal: dict, path: str) -> dict:
    record = next((item for item in proposal.get("files", []) if item["path"] == path), None)
    if not record:
        raise KeyError(f"Proposal file not found: {path}")
    return record


def get_diff(project: str, proposal_id: str, path: str) -> dict:
    _, proposal = _find(project, proposal_id)
    record = _file(proposal, path)
    before = safe_path(project, record["before_blob"]).read_text(encoding="utf-8")
    after = safe_path(project, record["after_blob"]).read_text(encoding="utf-8")
    return {
        **record,
        "change_id": f"proposal:{proposal_id}:{path}",
        "proposal_id": proposal_id,
        "run_id": proposal.get("run_id"),
        "source": "bob_model",
        "review_status": proposal.get("review_status"),
        "risk": proposal.get("risk"),
        "status": "conflict" if record.get("status") == "conflict" else "proposed",
        "before_content": before,
        "after_content": after,
        "diff": _diff(path, before, after),
        "hunks": [],
    }


def get_preview(project: str, proposal_id: str, path: str) -> dict:
    """Return virtual proposed file content without touching the workspace."""
    _, proposal = _find(project, proposal_id)
    record = _file(proposal, path)
    before = safe_path(project, record["before_blob"]).read_text(encoding="utf-8")
    after = safe_path(project, record["after_blob"]).read_text(encoding="utf-8")
    return {
        **record,
        "project": project,
        "proposal_id": proposal_id,
        "run_id": proposal.get("run_id"),
        "source": "bob_model",
        "virtual_uri": f"bob-proposal://{proposal_id}/{path}",
        "path": path,
        "content": after,
        "before_content": before,
        "review_status": proposal.get("review_status"),
        "risk": proposal.get("risk"),
        "summary": proposal.get("summary"),
        "status": "conflict" if record.get("status") == "conflict" else "proposed",
    }


def apply_proposal(project: str, proposal_id: str, path: str | None = None, override: bool = False) -> dict:
    with project_lock(project):
        data, proposal = _find(project, proposal_id)
        selected = [_file(proposal, path)] if path else [item for item in proposal["files"] if item.get("status") in {"proposed", "conflict"}]
        applied, conflicts = [], []
        for record in selected:
            target = safe_path(project, record["path"])
            current = target.read_text(encoding="utf-8") if target.is_file() else None
            if not override and _hash(current) != record["before_hash"]:
                record["status"] = "conflict"
                conflicts.append(record["path"])
                continue
            after = safe_path(project, record["after_blob"]).read_text(encoding="utf-8")
            if record["action"] == "delete":
                if target.exists():
                    target.unlink()
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(after, encoding="utf-8")
            record["status"] = "applied"
            applied.append(record["path"])
        states = {item.get("status") for item in proposal["files"]}
        proposal["status"] = "applied" if states == {"applied"} else "conflict" if "conflict" in states else "proposed"
        proposal["updated_at"] = _now()
        save_json_atomic(_bob(project) / "proposals" / proposal_id / "metadata.json", proposal)
        _save(project, data)
        return {"project": project, "proposal_id": proposal_id, "applied": applied, "conflicts": conflicts, "proposal": proposal}


def discard_proposal(project: str, proposal_id: str, path: str | None = None) -> dict:
    with project_lock(project):
        data, proposal = _find(project, proposal_id)
        selected = [_file(proposal, path)] if path else proposal["files"]
        for record in selected:
            if record.get("status") in {"proposed", "conflict"}:
                record["status"] = "discarded"
        active = [item for item in proposal["files"] if item.get("status") in {"proposed", "conflict"}]
        proposal["status"] = "proposed" if active else "discarded"
        proposal["updated_at"] = _now()
        save_json_atomic(_bob(project) / "proposals" / proposal_id / "metadata.json", proposal)
        _save(project, data)
        return {"project": project, "proposal_id": proposal_id, "proposal": proposal}


def apply_all(project: str, only_passing: bool = True) -> dict:
    results = []
    for proposal in list_proposals(project)["proposals"]:
        if only_passing and proposal.get("review_status") == "FAIL":
            continue
        results.append(apply_proposal(project, proposal["proposal_id"]))
    return {"project": project, "results": results}


def discard_all(project: str) -> dict:
    results = [discard_proposal(project, item["proposal_id"]) for item in list_proposals(project)["proposals"]]
    return {"project": project, "results": results}


def proposal_rows(project: str) -> list[dict]:
    rows = []
    for proposal in list_proposals(project)["proposals"]:
        for record in proposal.get("files", []):
            if record.get("status") not in {"proposed", "conflict"}:
                continue
            rows.append({
                **record,
                "change_id": f"proposal:{proposal['proposal_id']}:{record['path']}",
                "proposal_id": proposal["proposal_id"],
                "run_id": proposal.get("run_id"),
                "source": "bob_model",
                "review_status": proposal.get("review_status"),
                "risk": proposal.get("risk"),
                "summary": proposal.get("summary"),
                "status": "conflict" if record.get("status") == "conflict" else "proposed",
            })
    return rows
