from pathlib import Path
from typing import Dict, List

from bob_core.command_runner import run_python as _run_python
from bob_core.file_manager import (
    create_file as _create_file,
    delete_file as _delete_file,
    list_files as _list_files,
    read_file as _read_file,
    rename_file as _rename_file,
    safe_path,
    save_file as _save_file,
)

DEFAULT_PROJECT = "sample_project"


def list_files(project: str = DEFAULT_PROJECT) -> List[str]:
    return _list_files(project)


def read_file(path: str, project: str = DEFAULT_PROJECT) -> str:
    return _read_file(project, path)["content"]


def write_file(path: str, content: str, project: str = DEFAULT_PROJECT) -> Dict:
    return _save_file(project, path, content)


def create_file(path: str, project: str = DEFAULT_PROJECT) -> Dict:
    return _create_file(project, path)


def delete_file(path: str, project: str = DEFAULT_PROJECT) -> Dict:
    return _delete_file(project, path)


def rename_file(path: str, new_path: str, project: str = DEFAULT_PROJECT) -> Dict:
    return _rename_file(project, path, new_path)


def search_workspace(text: str, project: str = DEFAULT_PROJECT) -> List[Dict]:
    needle = text.lower()
    if not needle:
        return []

    root = safe_path(project)
    matches = []
    for rel_path in list_files(project):
        path = root / rel_path
        try:
            lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            continue
        for line_no, line in enumerate(lines, start=1):
            if needle in line.lower():
                matches.append({"file": rel_path, "line": line_no, "match": line.strip()})
    return matches


def run_python(file: str, project: str = DEFAULT_PROJECT) -> Dict:
    return _run_python(project, file)
