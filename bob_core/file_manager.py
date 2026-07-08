from pathlib import Path
from typing import Dict, List
from config import ALLOWED_EXTENSIONS, ALLOWED_FILENAMES, IGNORED_DIRS, MAX_FILE_SIZE, WORKSPACE_DIR


def safe_path(project: str, rel_path: str = "") -> Path:
    workspace_root = WORKSPACE_DIR.resolve()
    root = (workspace_root / project).resolve()
    if root == workspace_root or workspace_root not in root.parents:
        raise ValueError("Invalid workspace project")
    target = (root / rel_path).resolve()
    if root != target and root not in target.parents:
        raise ValueError("Path escapes selected workspace project")
    return target


def is_allowed_text_file(path: Path) -> bool:
    return not path.suffix or path.suffix in ALLOWED_EXTENSIONS or path.name in ALLOWED_FILENAMES


def list_projects() -> List[str]:
    WORKSPACE_DIR.mkdir(parents=True, exist_ok=True)
    return sorted([p.name for p in WORKSPACE_DIR.iterdir() if p.is_dir()])


def scan_tree(project: str) -> Dict:
    root = safe_path(project)

    def walk(path: Path):
        children = []
        for item in sorted(path.iterdir(), key=lambda p: (p.is_file(), p.name.lower())):
            rel = item.relative_to(root).as_posix()
            if item.is_dir():
                if item.name.startswith(".") or item.name in IGNORED_DIRS:
                    continue
                children.append({"name": item.name, "path": rel, "type": "folder", "children": walk(item)})
            else:
                if item.name.startswith(".") and not is_allowed_text_file(item):
                    continue
                children.append({"name": item.name, "path": rel, "type": "file", "ext": item.suffix})
        return children

    return {"name": project, "path": "", "type": "workspace", "children": walk(root)}


def list_files(project: str) -> List[str]:
    root = safe_path(project)
    files = []
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        parts = path.relative_to(root).parts
        if any(part in IGNORED_DIRS or (part.startswith(".") and part != path.name) for part in parts):
            continue
        if is_allowed_text_file(path):
            files.append(path.relative_to(root).as_posix())
    return files


def read_file(project: str, rel_path: str) -> Dict:
    path = safe_path(project, rel_path)
    if not path.exists() or not path.is_file():
        raise FileNotFoundError("File not found")
    if not is_allowed_text_file(path):
        raise ValueError(f"File type not allowed: {path.suffix or path.name}")
    if path.stat().st_size > MAX_FILE_SIZE:
        raise ValueError("File is too large for the web editor")
    return {"path": rel_path, "content": path.read_text(encoding="utf-8"), "ext": path.suffix}


def save_file(project: str, rel_path: str, content: str) -> Dict:
    path = safe_path(project, rel_path)
    if not is_allowed_text_file(path):
        raise ValueError(f"File type not allowed: {path.suffix or path.name}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return {"saved": True, "path": rel_path}


def create_file(project: str, rel_path: str) -> Dict:
    path = safe_path(project, rel_path)
    if path.exists():
        raise FileExistsError("File already exists")
    if not is_allowed_text_file(path):
        raise ValueError(f"File type not allowed: {path.suffix or path.name}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("", encoding="utf-8")
    return {"created": True, "path": rel_path}


def create_folder(project: str, rel_path: str) -> Dict:
    path = safe_path(project, rel_path)
    path.mkdir(parents=True, exist_ok=False)
    return {"created": True, "path": rel_path}


def delete_file(project: str, rel_path: str) -> Dict:
    path = safe_path(project, rel_path)
    if not path.exists() or not path.is_file():
        raise FileNotFoundError("File not found")
    if not is_allowed_text_file(path):
        raise ValueError(f"File type not allowed: {path.suffix or path.name}")
    path.unlink()
    return {"deleted": True, "path": rel_path}


def rename_file(project: str, rel_path: str, new_rel_path: str) -> Dict:
    source = safe_path(project, rel_path)
    target = safe_path(project, new_rel_path)
    if not source.exists() or not source.is_file():
        raise FileNotFoundError("File not found")
    if target.exists():
        raise FileExistsError("Target already exists")
    if not is_allowed_text_file(target):
        raise ValueError(f"File type not allowed: {target.suffix or target.name}")
    target.parent.mkdir(parents=True, exist_ok=True)
    source.rename(target)
    return {"renamed": True, "path": rel_path, "new_path": new_rel_path}


def delete_folder(project: str, rel_path: str) -> Dict:
    path = safe_path(project, rel_path)
    if not rel_path or path == safe_path(project):
        raise ValueError("Cannot delete the workspace root")
    if not path.exists() or not path.is_dir():
        raise FileNotFoundError("Folder not found")
    import shutil

    shutil.rmtree(path)
    return {"deleted": True, "path": rel_path}


def rename_folder(project: str, rel_path: str, new_rel_path: str) -> Dict:
    source = safe_path(project, rel_path)
    target = safe_path(project, new_rel_path)
    if not rel_path or source == safe_path(project):
        raise ValueError("Cannot rename the workspace root")
    if not source.exists() or not source.is_dir():
        raise FileNotFoundError("Folder not found")
    if target.exists():
        raise FileExistsError("Target already exists")
    target.parent.mkdir(parents=True, exist_ok=True)
    source.rename(target)
    return {"renamed": True, "path": rel_path, "new_path": new_rel_path}


def rename_path(project: str, rel_path: str, new_rel_path: str) -> Dict:
    """Rename either a file or a folder, dispatching by what's on disk."""
    source = safe_path(project, rel_path)
    if source.is_dir():
        return rename_folder(project, rel_path, new_rel_path)
    return rename_file(project, rel_path, new_rel_path)


def delete_path(project: str, rel_path: str) -> Dict:
    """Delete either a file or a folder, dispatching by what's on disk."""
    source = safe_path(project, rel_path)
    if source.is_dir():
        return delete_folder(project, rel_path)
    return delete_file(project, rel_path)
