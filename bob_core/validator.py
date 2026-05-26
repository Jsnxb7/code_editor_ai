import ast
import json
from pathlib import Path


def validate_python(code: str):
    problems = []
    try:
        tree = ast.parse(code)
    except SyntaxError as exc:
        return [{"line": exc.lineno or 1, "severity": "error", "message": exc.msg}]

    imported = set()
    used_names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imported.add(alias.asname or alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            for alias in node.names:
                imported.add(alias.asname or alias.name)
        elif isinstance(node, ast.Name):
            used_names.add(node.id)

    hints = {
        "request": "request is used but not imported from flask",
        "session": "session is used but not imported from flask",
        "json": "json is used but not imported",
        "render_template": "render_template is used but not imported from flask",
        "redirect": "redirect is used but not imported from flask",
        "url_for": "url_for is used but not imported from flask",
    }
    for name, message in hints.items():
        if name in used_names and name not in imported:
            problems.append({"line": 1, "severity": "warning", "message": message})

    if "app.run(" in code and "debug=True" in code and "use_reloader=False" not in code:
        problems.append({
            "line": 1,
            "severity": "warning",
            "message": "Flask debug reloader may fail inside Bob IDE on Windows. Use app.run(debug=False, use_reloader=False, port=7000)."
        })

    return problems


def validate_json(code: str):
    try:
        json.loads(code)
        return []
    except json.JSONDecodeError as exc:
        return [{"line": exc.lineno, "severity": "error", "message": exc.msg}]


def validate_file(rel_path: str, content: str):
    suffix = Path(rel_path).suffix.lower()
    problems = []
    if suffix == ".py":
        problems.extend(validate_python(content))
    elif suffix == ".json":
        problems.extend(validate_json(content))
    if "{" in content and "}" in content and any(token in content for token in ["{json_file}", "{lookup_key}", "{return_key}"]):
        problems.append({"line": 1, "severity": "warning", "message": "Template placeholders are still unfilled"})
    return problems
