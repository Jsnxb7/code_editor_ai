"""Deterministic context builder for staged Bob model phases."""

from __future__ import annotations

from typing import Any

from bob_core.file_manager import list_files, read_file, scan_tree, safe_path
from workspace_tools import search_workspace

DEFAULT_MAX_BYTES = 500_000


def _normalize(path: str | None) -> str:
    value = str(path or "").replace("\\", "/").strip().lstrip("/")
    parts: list[str] = []
    for part in value.split("/"):
        if not part or part == "." or part == "..":
            continue
        parts.append(part)
    return "/".join(parts)


def _safe_unique(paths: list[str | None]) -> list[str]:
    seen, output = set(), []
    for path in paths:
        normalized = _normalize(path)
        if not normalized or normalized in seen or normalized.startswith(".bob/") or "/.bob/" in normalized:
            continue
        seen.add(normalized)
        output.append(normalized)
    return output


def build_context(
    project: str,
    prompt: str = "",
    active_path: str | None = None,
    forced_paths: list[str] | None = None,
    open_paths: list[str] | None = None,
    forced_files: dict[str, str] | None = None,
    plan: dict[str, Any] | None = None,
    max_bytes: int = DEFAULT_MAX_BYTES,
) -> dict[str, Any]:
    """Build payload for Colab.

    Priority: forced files -> active file -> open tabs -> plan requested files -> search-related files -> rest.
    Forced files are always attempted first; if they exceed budget, a marker is returned in skipped_paths.
    """
    forced_paths = _safe_unique(forced_paths or [])
    open_paths = _safe_unique(open_paths or [])
    incoming_forced_files = { _normalize(path): str(content or "") for path, content in (forced_files or {}).items() if _normalize(path) }
    active_path = _normalize(active_path)
    plan = plan or {}
    visible = set(list_files(project))
    requested = _safe_unique((plan.get("files_needed") or []) + (plan.get("required_context") or []))

    search_hits: list[str] = []
    if prompt.strip():
        try:
            matches = search_workspace(prompt[:120], project)[:12]
            search_hits = _safe_unique([item.get("path") for item in matches])
        except Exception:
            search_hits = []

    ordered = _safe_unique([
        *forced_paths,
        active_path,
        *open_paths,
        *requested,
        *search_hits,
        *sorted(visible),
    ])

    files: dict[str, str] = {}
    forced_files_out: dict[str, str] = {}
    skipped_paths: list[dict[str, Any]] = []
    max_bytes = max(20_000, min(int(max_bytes or DEFAULT_MAX_BYTES), 2_000_000))
    total = 0

    # User-forced files may be sent by the IDE as text. This avoids Colab/local
    # path access issues and keeps the context payload deterministic.
    for path in forced_paths:
        if path not in incoming_forced_files:
            continue
        content = incoming_forced_files[path]
        size = len(content.encode("utf-8", errors="replace"))
        if total + size > max_bytes:
            allowed = max(0, max_bytes - total)
            content = content[:allowed] + "\n/* CONTEXT TRUNCATED BY BYTE BUDGET */\n"
            size = len(content.encode("utf-8", errors="replace"))
            skipped_paths.append({"path": path, "reason": "forced_text_truncated", "size": size})
        files[path] = content
        forced_files_out[path] = content
        total += size
        if total >= max_bytes:
            break
    for path in ordered:
        if path in files:
            continue
        if path not in visible:
            skipped_paths.append({"path": path, "reason": "not_found_or_not_editable"})
            continue
        try:
            content = read_file(project, path)["content"]
        except Exception as exc:
            skipped_paths.append({"path": path, "reason": str(exc)})
            continue
        size = len(content.encode("utf-8", errors="replace"))
        if total + size > max_bytes and path not in forced_paths:
            skipped_paths.append({"path": path, "reason": "budget_exceeded", "size": size})
            continue
        if total + size > max_bytes and path in forced_paths:
            # Forced files are more important than auto context; include a truncated marker instead of silently dropping.
            allowed = max(0, max_bytes - total)
            content = content[:allowed] + "\n/* CONTEXT TRUNCATED BY BYTE BUDGET */\n"
            size = len(content.encode("utf-8", errors="replace"))
            skipped_paths.append({"path": path, "reason": "forced_truncated", "size": size})
        files[path] = content
        if path in forced_paths:
            forced_files_out[path] = content
        total += size
        if total >= max_bytes:
            break

    return {
        "project": project,
        "prompt": prompt,
        "active_path": active_path,
        "workspace_tree": scan_tree(project),
        "files": files,
        "forced_files": forced_files_out,
        "forced_paths": forced_paths,
        "selected_paths": list(files.keys()),
        "skipped_paths": skipped_paths,
        "total_bytes": total,
        "max_bytes": max_bytes,
        "context_policy": {
            "mode": "staged",
            "include_active_file": bool(active_path),
            "include_forced_files": True,
            "priority": ["forced", "active", "open", "plan", "search", "workspace"],
        },
    }
