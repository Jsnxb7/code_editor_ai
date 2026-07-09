"""One-time JSON-worktree to Git/proposal migration."""

from __future__ import annotations

import json
import os
import shutil
from datetime import datetime, timezone
from pathlib import Path

from bob_core.file_manager import safe_path
from bob_core.json_store import load_json
from bob_core import git_service, proposal_store


def _load(path: Path, default):
    return load_json(path, default)


def _snapshot_payload(root: Path, snapshot_id: str) -> dict[str, str]:
    payload = _load(root / ".bob" / "snapshots" / f"{snapshot_id}.json", {"files": {}})
    return payload.get("files", {})


def _write_commit_tree(project: str, files: dict[str, str], index_path: Path) -> str:
    env = {"GIT_INDEX_FILE": str(index_path)}
    git_service.run_git(project, ["read-tree", "--empty"], check=True, env=env)
    for path, content in files.items():
        blob = git_service.run_git(project, ["hash-object", "-w", "--stdin"], check=True, input_text=content)["stdout"].strip()
        git_service.run_git(
            project,
            ["update-index", "--add", "--cacheinfo", f"100644,{blob},{path}"],
            check=True,
            env=env,
        )
    return git_service.run_git(project, ["write-tree"], check=True, env=env)["stdout"].strip()


def migrate_json_worktree(project: str) -> dict:
    root = safe_path(project)
    bob = root / ".bob"
    marker = bob / "git-migration.json"
    if marker.exists():
        return _load(marker, {"migrated": True})

    legacy_exists = (bob / "snapshots.json").exists() or (bob / "changes.json").exists()
    git_service.init_repo(project)
    if not legacy_exists:
        result = {"project": project, "migrated": True, "legacy": False}
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
        return result

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup = bob / "legacy-json-worktree" / timestamp
    backup.mkdir(parents=True, exist_ok=True)
    for name in ("index.json", "changes.json", "staged.json", "snapshots.json", ".bobignore"):
        source = bob / name
        if source.exists():
            shutil.copy2(source, backup / name)
    for name in ("snapshots", "change_blobs", "patches"):
        source = bob / name
        if source.exists():
            shutil.copytree(source, backup / name, dirs_exist_ok=True)

    snapshots = _load(bob / "snapshots.json", {"snapshots": []}).get("snapshots", [])
    temp_index = bob / f".migration-index-{os.getpid()}"
    parent = None
    migrated_commits = []
    try:
        for snapshot in snapshots:
            files = _snapshot_payload(root, snapshot["snapshot_id"])
            tree = _write_commit_tree(project, files, temp_index)
            args = ["commit-tree", tree, "-m", snapshot.get("message") or snapshot.get("label") or "Migrated checkpoint"]
            if parent:
                args.extend(["-p", parent])
            created = snapshot.get("created_at") or datetime.now(timezone.utc).isoformat()
            env = {
                "GIT_AUTHOR_NAME": "Bob IDE Migration",
                "GIT_AUTHOR_EMAIL": "bob@localhost",
                "GIT_COMMITTER_NAME": "Bob IDE Migration",
                "GIT_COMMITTER_EMAIL": "bob@localhost",
                "GIT_AUTHOR_DATE": created,
                "GIT_COMMITTER_DATE": created,
            }
            parent = git_service.run_git(project, args, check=True, env=env)["stdout"].strip()
            migrated_commits.append(parent)
        if parent:
            git_service.run_git(project, ["update-ref", "refs/heads/main", parent], check=True)
            git_service.run_git(project, ["reset", "--mixed", parent], check=True)

        changes = _load(bob / "changes.json", {"changes": []}).get("changes", [])
        grouped: dict[str, list[dict]] = {}
        for change in changes:
            if change.get("source") == "bob_model" and change.get("status") in {"proposed", "conflict"}:
                grouped.setdefault(change.get("run_id") or change["change_id"], []).append(change)
        migrated_proposals = []
        for run_id, items in grouped.items():
            files, before_files = {}, {}
            for item in items:
                before_path = safe_path(project, item["before_blob"])
                after_path = safe_path(project, item["after_blob"])
                before_files[item["path"]] = before_path.read_text(encoding="utf-8") if before_path.exists() else None
                files[item["path"]] = None if item.get("action") == "delete" else after_path.read_text(encoding="utf-8")
            proposal = proposal_store.create_proposal(
                project,
                run_id,
                files,
                items[0].get("review_status", "PASS"),
                before_files=before_files,
            )
            migrated_proposals.append(proposal["proposal_id"])

        staged = _load(bob / "staged.json", {"staged": []}).get("staged", [])
        for item in staged:
            path = item["path"]
            if item.get("action") == "delete":
                git_service.run_git(project, ["rm", "--cached", "--ignore-unmatch", "--", path], check=True)
                continue
            blob_path = safe_path(project, item.get("after_blob", ""))
            if blob_path.exists():
                blob = git_service.run_git(project, ["hash-object", "-w", "--stdin"], check=True, input_text=blob_path.read_text(encoding="utf-8"))["stdout"].strip()
                git_service.run_git(project, ["update-index", "--add", "--cacheinfo", f"100644,{blob},{path}"], check=True)

        result = {
            "project": project,
            "migrated": True,
            "legacy": True,
            "backup": str(backup.relative_to(root)).replace("\\", "/"),
            "commits": migrated_commits,
            "proposals": migrated_proposals,
            "migrated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        }
        marker.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
        return result
    finally:
        if temp_index.exists():
            temp_index.unlink()
