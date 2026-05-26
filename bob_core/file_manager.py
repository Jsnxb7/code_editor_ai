from pathlib import Path
from typing import Dict, List
from config import WORKSPACE_DIR, ALLOWED_EXTENSIONS, MAX_FILE_SIZE


def safe_path(project: str, rel_path: str = "") -> Path:
    root = (WORKSPACE_DIR / project).resolve()
    target = (root / rel_path).resolve()
    if root != target and root not in target.parents:
        raise ValueError("Path escapes selected workspace project")
    return target


def list_projects() -> List[str]:
    WORKSPACE_DIR.mkdir(parents=True, exist_ok=True)
    return sorted([p.name for p in WORKSPACE_DIR.iterdir() if p.is_dir()])


def scan_tree(project: str) -> Dict:
    root = safe_path(project)

    def walk(path: Path):
        children = []
        for item in sorted(path.iterdir(), key=lambda p: (p.is_file(), p.name.lower())):
            if item.name.startswith(".") or item.name in {"__pycache__", "node_modules", "venv", ".venv"}:
                continue
            rel = item.relative_to(root).as_posix()
            if item.is_dir():
                children.append({"name": item.name, "path": rel, "type": "folder", "children": walk(item)})
            else:
                children.append({"name": item.name, "path": rel, "type": "file", "ext": item.suffix})
        return children

    return {"name": project, "path": "", "type": "workspace", "children": walk(root)}


def read_file(project: str, rel_path: str) -> Dict:
    path = safe_path(project, rel_path)
    if not path.exists() or not path.is_file():
        raise FileNotFoundError("File not found")
    if path.suffix not in ALLOWED_EXTENSIONS:
        raise ValueError(f"File type not allowed: {path.suffix}")
    if path.stat().st_size > MAX_FILE_SIZE:
        raise ValueError("File is too large for the web editor")
    return {"path": rel_path, "content": path.read_text(encoding="utf-8"), "ext": path.suffix}


def save_file(project: str, rel_path: str, content: str) -> Dict:
    path = safe_path(project, rel_path)
    if path.suffix not in ALLOWED_EXTENSIONS:
        raise ValueError(f"File type not allowed: {path.suffix}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return {"saved": True, "path": rel_path}


def create_file(project: str, rel_path: str) -> Dict:
    path = safe_path(project, rel_path)
    if path.exists():
        raise FileExistsError("File already exists")
    if path.suffix not in ALLOWED_EXTENSIONS:
        raise ValueError(f"File type not allowed: {path.suffix}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("", encoding="utf-8")
    return {"created": True, "path": rel_path}


def create_folder(project: str, rel_path: str) -> Dict:
    path = safe_path(project, rel_path)
    path.mkdir(parents=True, exist_ok=False)
    return {"created": True, "path": rel_path}
