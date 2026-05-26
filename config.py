from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
WORKSPACE_DIR = BASE_DIR / "workspace"
DATA_DIR = BASE_DIR / "data"
ALLOWED_EXTENSIONS = {
    ".py", ".html", ".css", ".js", ".json", ".md", ".txt", ".yml", ".yaml"
}
MAX_FILE_SIZE = 1024 * 1024 * 2
