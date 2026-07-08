from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
WORKSPACE_DIR = BASE_DIR / "workspace"
DATA_DIR = BASE_DIR / "data"
FRONTEND_DIST_DIR = BASE_DIR / "frontend" / "dist"
ALLOWED_EXTENSIONS = {
    ".bat",
    ".c",
    ".cfg",
    ".cpp",
    ".cs",
    ".css",
    ".go",
    ".h",
    ".hpp",
    ".html",
    ".ini",
    ".java",
    ".js",
    ".jsx",
    ".json",
    ".less",
    ".lua",
    ".md",
    ".php",
    ".ps1",
    ".py",
    ".rb",
    ".rs",
    ".sass",
    ".scss",
    ".sh",
    ".sql",
    ".svg",
    ".toml",
    ".ts",
    ".tsx",
    ".txt",
    ".xml",
    ".yaml",
    ".yml",
}
ALLOWED_FILENAMES = {
    ".env",
    ".gitignore",
    "Dockerfile",
    "Makefile",
    "README",
}
MAX_FILE_SIZE = 1024 * 1024 * 2
SEARCH_EXTENSIONS = ALLOWED_EXTENSIONS
IGNORED_DIRS = {"__pycache__", "node_modules", "venv", ".venv", ".git", ".bob", ".pytest_cache"}
