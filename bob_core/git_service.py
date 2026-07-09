"""Git-backed source control for isolated Bob IDE workspaces."""

from __future__ import annotations

import difflib
import json
import os
import subprocess
from pathlib import Path
from typing import Any

from bob_core.file_manager import safe_path


DEFAULT_GITIGNORE = [
    ".bob/proposals/",
    ".bob/legacy-json-worktree/",
    ".bob/runs.json",
    ".bob/model_runs.json",
    ".bob/chat_history.json",
    ".bob/model_config.json",
    ".bob/tmp/",
    ".bob/model_cache/",
    "node_modules/",
    "dist/",
    "build/",
    ".venv/",
    "venv/",
    "__pycache__/",
    "*.pyc",
    ".env",
    ".env.local",
]


def _root(project: str) -> Path:
    return safe_path(project)


def run_git(
    project: str,
    args: list[str],
    *,
    check: bool = False,
    input_text: str | None = None,
    env: dict[str, str] | None = None,
) -> dict[str, Any]:
    root = _root(project)
    result = subprocess.run(
        ["git", "-c", f"safe.directory={root}", *args],
        cwd=str(root),
        input=input_text,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        shell=False,
        env={**os.environ, **(env or {})},
    )
    payload = {
        "ok": result.returncode == 0,
        "code": result.returncode,
        "stdout": result.stdout,
        "stderr": result.stderr,
        "args": args,
    }
    if check and result.returncode != 0:
        raise RuntimeError((result.stderr or result.stdout or "Git command failed").strip())
    return payload


def is_git_repo(project: str) -> dict[str, Any]:
    root = _root(project).resolve()
    if not (root / ".git").exists():
        return {"project": project, "is_repo": False, "root": str(root)}
    result = run_git(project, ["rev-parse", "--show-toplevel"])
    top = Path(result["stdout"].strip()).resolve() if result["ok"] and result["stdout"].strip() else None
    return {
        "project": project,
        "is_repo": bool(top == root),
        "root": str(root),
        "git_root": str(top) if top else None,
    }


def _append_default_ignore(project: str) -> None:
    path = _root(project) / ".gitignore"
    existing = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    changed = False
    for pattern in DEFAULT_GITIGNORE:
        if pattern not in existing:
            existing.append(pattern)
            changed = True
    if changed:
        path.write_text("\n".join(existing).rstrip() + "\n", encoding="utf-8", newline="\n")


def init_repo(project: str) -> dict[str, Any]:
    state = is_git_repo(project)
    if not state["is_repo"]:
        result = run_git(project, ["init", "-b", "main"])
        if not result["ok"]:
            run_git(project, ["init"], check=True)
            run_git(project, ["branch", "-M", "main"], check=True)
    _append_default_ignore(project)
    return get_status(project)


def _ensure_repo(project: str) -> None:
    if not is_git_repo(project)["is_repo"]:
        raise RuntimeError("Workspace is not an isolated Git repository")


def _has_head(project: str) -> bool:
    return run_git(project, ["rev-parse", "--verify", "HEAD"])["ok"]


def _action(index_code: str, worktree_code: str, *, untracked: bool = False) -> str:
    code = index_code if index_code not in {".", " "} else worktree_code
    if untracked or code in {"A", "?"}:
        return "add"
    if code == "D":
        return "delete"
    if code in {"R", "C"}:
        return "rename"
    return "modify"


def _entry(project: str, path: str, group: str, xy: str, original_path: str | None = None) -> dict:
    index_code, worktree_code = xy[0], xy[1]
    staged = group == "staged"
    untracked = group == "untracked"
    action = _action(index_code, worktree_code, untracked=untracked)
    return {
        "change_id": f"git:{'staged' if staged else group}:{path}",
        "source": "git",
        "path": path,
        "original_path": original_path,
        "action": action,
        "status": "staged" if staged else "conflict" if group == "conflicts" else "unstaged",
        "git_group": group,
        "git_xy": xy,
        "staged": staged,
        "untracked": untracked,
        "letter": "U" if untracked else {"add": "A", "delete": "D", "rename": "R"}.get(action, "M"),
    }


def get_status(project: str) -> dict[str, Any]:
    _ensure_repo(project)
    result = run_git(
        project,
        ["status", "--porcelain=v2", "-z", "--branch", "--untracked-files=all"],
        check=True,
    )
    groups: dict[str, list[dict]] = {
        "conflicts": [],
        "changes": [],
        "untracked": [],
        "staged": [],
    }
    branch = "main"
    oid = None
    upstream = None
    ahead = behind = 0
    records = result["stdout"].split("\0")
    index = 0
    while index < len(records):
        record = records[index]
        index += 1
        if not record:
            continue
        if record.startswith("# branch.head "):
            branch = record.removeprefix("# branch.head ").strip()
            continue
        if record.startswith("# branch.oid "):
            value = record.removeprefix("# branch.oid ").strip()
            oid = None if value == "(initial)" else value
            continue
        if record.startswith("# branch.upstream "):
            upstream = record.removeprefix("# branch.upstream ").strip()
            continue
        if record.startswith("# branch.ab "):
            parts = record.split()
            ahead = int(parts[2][1:])
            behind = int(parts[3][1:])
            continue
        if record.startswith("? "):
            path = record[2:]
            groups["untracked"].append(_entry(project, path, "untracked", "??"))
            continue
        if record.startswith("u "):
            parts = record.split(" ", 10)
            path = parts[-1]
            xy = parts[1]
            groups["conflicts"].append(_entry(project, path, "conflicts", xy))
            continue
        if record.startswith(("1 ", "2 ")):
            parts = record.split(" ", 8 if record.startswith("1 ") else 9)
            xy = parts[1]
            path = parts[-1]
            original = None
            if record.startswith("2 ") and index < len(records):
                original = records[index]
                index += 1
            if xy[0] not in {".", " "}:
                groups["staged"].append(_entry(project, path, "staged", xy, original))
            if xy[1] not in {".", " "}:
                groups["changes"].append(_entry(project, path, "changes", xy, original))

    summary = {key: len(value) for key, value in groups.items()}
    total = sum(summary.values())
    return {
        "project": project,
        "is_repo": True,
        "state": "clean" if total == 0 else "conflict" if groups["conflicts"] else "dirty",
        "branch": branch,
        "head": oid,
        "upstream": upstream,
        "ahead": ahead,
        "behind": behind,
        "has_conflicts": bool(groups["conflicts"]),
        "summary": summary,
        **groups,
    }


def _git_text(project: str, spec: str) -> str:
    result = run_git(project, ["show", spec])
    return result["stdout"] if result["ok"] else ""


def _working_text(project: str, path: str) -> str:
    target = safe_path(project, path)
    if not target.is_file():
        return ""
    try:
        return target.read_text(encoding="utf-8")
    except (UnicodeDecodeError, OSError):
        return ""


def _unified(path: str, before: str, after: str) -> str:
    return "".join(
        difflib.unified_diff(
            before.splitlines(keepends=True),
            after.splitlines(keepends=True),
            fromfile=f"a/{path}",
            tofile=f"b/{path}",
        )
    )


def _hunks(patch: str) -> list[dict[str, Any]]:
    hunks = []
    current: list[str] = []
    header = ""
    for line in patch.splitlines(keepends=True):
        if line.startswith("@@ "):
            if current:
                hunks.append((header, "".join(current)))
            header, current = line.rstrip(), [line]
        elif current:
            current.append(line)
    if current:
        hunks.append((header, "".join(current)))
    output = []
    import re

    for position, (value, text) in enumerate(hunks, start=1):
        match = re.search(r"@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))?", value)
        if not match:
            continue
        output.append({
            "hunk_id": f"hunk_{position:04d}",
            "status": "pending",
            "old_start": int(match.group(1)),
            "old_lines": int(match.group(2) or 1),
            "new_start": int(match.group(3)),
            "new_lines": int(match.group(4) or 1),
            "diff": text,
        })
    return output


def get_diff(project: str, path: str, staged: bool = False, conflict: bool = False) -> dict[str, Any]:
    _ensure_repo(project)
    safe_path(project, path)
    if conflict:
        base = _git_text(project, f":1:{path}")
        current = _git_text(project, f":2:{path}")
        incoming = _git_text(project, f":3:{path}")
        return {
            "change_id": f"git:conflicts:{path}",
            "source": "git",
            "path": path,
            "status": "conflict",
            "before_content": base,
            "after_content": current,
            "incoming_content": incoming,
            "diff": _unified(path, base, current),
            "hunks": [],
        }
    before = _git_text(project, f"HEAD:{path}") if staged and _has_head(project) else (
        _git_text(project, f":{path}") if not staged else ""
    )
    after = _git_text(project, f":{path}") if staged else _working_text(project, path)
    patch_args = ["diff", "--cached"] if staged else ["diff"]
    patch = run_git(project, [*patch_args, "--", path], check=True)["stdout"]
    if not patch and not staged and not run_git(project, ["ls-files", "--error-unmatch", "--", path])["ok"]:
        patch = _unified(path, "", after)
    return {
        "change_id": f"git:{'staged' if staged else 'changes'}:{path}",
        "source": "git",
        "path": path,
        "status": "staged" if staged else "unstaged",
        "staged": staged,
        "before_content": before,
        "after_content": after,
        "diff": patch,
        "hunks": _hunks(patch),
    }


def stage_file(project: str, path: str) -> dict:
    safe_path(project, path)
    run_git(project, ["add", "--", path], check=True)
    return get_status(project)


def unstage_file(project: str, path: str) -> dict:
    safe_path(project, path)
    if _has_head(project):
        run_git(project, ["restore", "--staged", "--", path], check=True)
    else:
        run_git(project, ["rm", "--cached", "--ignore-unmatch", "--", path], check=True)
    return get_status(project)


def stage_all(project: str) -> dict:
    run_git(project, ["add", "-A"], check=True)
    return get_status(project)


def unstage_all(project: str) -> dict:
    if _has_head(project):
        run_git(project, ["reset", "--mixed", "HEAD"], check=True)
    else:
        run_git(project, ["rm", "-r", "--cached", "--ignore-unmatch", "."], check=True)
    return get_status(project)


def _hunk_patch(project: str, path: str, hunk_id: str, staged: bool = False) -> str:
    diff = get_diff(project, path, staged=staged)
    hunk = next((item for item in diff["hunks"] if item["hunk_id"] == hunk_id), None)
    if not hunk:
        raise KeyError(f"Hunk not found: {hunk_id}")
    return f"--- a/{path}\n+++ b/{path}\n{hunk['diff']}"


def _apply_hunk_content(content: str, hunk: dict, reverse: bool = False) -> str:
    old_block, new_block = [], []
    for line in hunk["diff"].splitlines(keepends=True)[1:]:
        if line.startswith("\\"):
            continue
        marker, value = line[:1], line[1:]
        if marker in {" ", "-"}:
            old_block.append(value)
        if marker in {" ", "+"}:
            new_block.append(value)
    source, replacement = (new_block, old_block) if reverse else (old_block, new_block)
    lines = content.splitlines(keepends=True)
    expected = max(0, (hunk["new_start"] if reverse else hunk["old_start"]) - 1)
    candidates = [expected, *range(max(0, expected - 8), min(len(lines), expected + 9))]
    for index in candidates:
        if lines[index:index + len(source)] == source:
            return "".join(lines[:index] + replacement + lines[index + len(source):])
    raise RuntimeError("Hunk no longer applies cleanly")


def stage_hunk(project: str, path: str, hunk_id: str) -> dict:
    diff = get_diff(project, path)
    hunk = next((item for item in diff["hunks"] if item["hunk_id"] == hunk_id), None)
    if not hunk:
        raise KeyError(f"Hunk not found: {hunk_id}")
    staged_content = _apply_hunk_content(diff["before_content"], hunk)
    blob = run_git(project, ["hash-object", "-w", "--stdin"], check=True, input_text=staged_content)["stdout"].strip()
    index_line = run_git(project, ["ls-files", "-s", "--", path])["stdout"].strip()
    mode = index_line.split()[0] if index_line else "100644"
    run_git(project, ["update-index", "--add", "--cacheinfo", f"{mode},{blob},{path}"], check=True)
    return get_status(project)


def discard_hunk(project: str, path: str, hunk_id: str) -> dict:
    diff = get_diff(project, path)
    hunk = next((item for item in diff["hunks"] if item["hunk_id"] == hunk_id), None)
    if not hunk:
        raise KeyError(f"Hunk not found: {hunk_id}")
    current = _working_text(project, path)
    restored = _apply_hunk_content(current, hunk, reverse=True)
    safe_path(project, path).write_text(restored, encoding="utf-8", newline="")
    return get_status(project)


def discard_file(project: str, path: str, *, staged: bool = False, untracked: bool = False) -> dict:
    target = safe_path(project, path)
    if untracked:
        if target.is_dir():
            import shutil
            shutil.rmtree(target)
        elif target.exists():
            target.unlink()
    elif staged:
        if not _has_head(project):
            run_git(project, ["rm", "--cached", "--ignore-unmatch", "--", path], check=True)
        else:
            run_git(project, ["restore", "--source=HEAD", "--staged", "--worktree", "--", path], check=True)
    else:
        run_git(project, ["restore", "--worktree", "--", path], check=True)
    return get_status(project)


def discard_all(project: str, include_untracked: bool = False) -> dict:
    if _has_head(project):
        run_git(project, ["restore", "--source=HEAD", "--staged", "--worktree", "."], check=True)
    else:
        run_git(project, ["rm", "-r", "--cached", "--ignore-unmatch", "."], check=True)
    if include_untracked:
        run_git(project, ["clean", "-fd"], check=True)
    return get_status(project)


def get_identity(project: str) -> dict:
    name = run_git(project, ["config", "--get", "user.name"])["stdout"].strip()
    email = run_git(project, ["config", "--get", "user.email"])["stdout"].strip()
    return {"name": name, "email": email, "configured": bool(name and email)}


def set_identity(project: str, name: str, email: str) -> dict:
    if not name.strip() or not email.strip():
        raise ValueError("Git author name and email are required")
    run_git(project, ["config", "user.name", name.strip()], check=True)
    run_git(project, ["config", "user.email", email.strip()], check=True)
    return get_identity(project)


def commit(project: str, message: str) -> dict:
    if not message.strip():
        raise ValueError("Commit message is required")
    if not get_identity(project)["configured"]:
        raise RuntimeError("GIT_IDENTITY_REQUIRED: Configure a Git author name and email")
    result = run_git(project, ["commit", "-m", message.strip()])
    if not result["ok"]:
        raise RuntimeError((result["stderr"] or result["stdout"]).strip())
    return {"commit": run_git(project, ["rev-parse", "HEAD"], check=True)["stdout"].strip(), "message": message.strip(), "status": get_status(project)}


def list_branches(project: str) -> dict:
    result = run_git(project, ["branch", "--format=%(refname:short)%00%(HEAD)"], check=True)
    branches = []
    for record in result["stdout"].splitlines():
        name, _, marker = record.partition("\0")
        branches.append({"name": name, "current": marker.strip() == "*"})
    return {"project": project, "branches": branches}


def create_branch(project: str, name: str, checkout: bool = True) -> dict:
    if not name.strip():
        raise ValueError("Branch name is required")
    run_git(project, ["check-ref-format", "--branch", name.strip()], check=True)
    run_git(project, ["switch", "-c", name.strip()] if checkout else ["branch", name.strip()], check=True)
    return {**list_branches(project), "status": get_status(project)}


def checkout_branch(project: str, name: str) -> dict:
    run_git(project, ["switch", name], check=True)
    return {**list_branches(project), "status": get_status(project)}


def get_log(project: str, limit: int = 50) -> dict:
    if not _has_head(project):
        return {"project": project, "commits": []}
    fmt = "%H%x00%h%x00%an%x00%ae%x00%aI%x00%s"
    result = run_git(project, ["log", f"--max-count={max(1, min(limit, 200))}", f"--format={fmt}"], check=True)
    commits = []
    for line in result["stdout"].splitlines():
        parts = line.split("\0")
        if len(parts) == 6:
            commits.append(dict(zip(("hash", "short_hash", "author", "email", "created_at", "message"), parts)))
    return {"project": project, "commits": commits}


def get_file_history(project: str, path: str, limit: int = 50) -> dict:
    safe_path(project, path)
    if not _has_head(project):
        return {"project": project, "path": path, "commits": []}
    fmt = "%H%x00%h%x00%an%x00%aI%x00%s"
    result = run_git(project, ["log", "--follow", f"--max-count={max(1, min(limit, 200))}", f"--format={fmt}", "--", path], check=True)
    commits = []
    for line in result["stdout"].splitlines():
        parts = line.split("\0")
        if len(parts) == 5:
            commits.append(dict(zip(("hash", "short_hash", "author", "created_at", "message"), parts)))
    return {"project": project, "path": path, "commits": commits}


def restore_file(project: str, path: str, ref: str = "HEAD") -> dict:
    safe_path(project, path)
    run_git(project, ["restore", f"--source={ref}", "--worktree", "--", path], check=True)
    return get_status(project)


def get_conflicts(project: str) -> dict:
    status = get_status(project)
    return {"project": project, "conflicts": status["conflicts"]}


def accept_conflict(project: str, path: str, side: str) -> dict:
    if side not in {"ours", "theirs"}:
        raise ValueError("Conflict side must be ours or theirs")
    run_git(project, ["checkout", f"--{side}", "--", path], check=True)
    run_git(project, ["add", "--", path], check=True)
    return get_status(project)


def generate_commit_message(project: str) -> dict:
    status = get_status(project)
    staged = status["staged"]
    if not staged:
        return {"message": ""}
    if len(staged) == 1:
        action = {"add": "Add", "delete": "Remove", "rename": "Rename"}.get(staged[0]["action"], "Update")
        return {"message": f"{action} {staged[0]['path']}"}
    return {"message": f"Update {len(staged)} files"}
