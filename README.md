# IBM Bob IDE v0.1

A web-based VS Code/Colab-inspired IDE foundation for the IBM Bob coding assistant.

## Completed Scope

This build covers phases 1 to 3:

1. Static IDE UI
   - VS Code-like layout
   - Workspace panel
   - Monaco code editor
   - Bob Assistant placeholder side panel
   - Bottom terminal/problems panel
   - Status bar

2. Real Workspace + Editor
   - Web-based workspace folder selection
   - Open files from `workspace/`
   - Create files
   - Create folders
   - Save files
   - Multiple language highlighting through Monaco

3. Run + Validate
   - Run Python files
   - Validate Python syntax with `ast.parse`
   - Validate JSON syntax
   - Show basic missing import warnings
   - Show problems in bottom panel

## Run Locally

```bash
pip install -r requirements.txt
python app.py
```

Then open:

```text
http://127.0.0.1:5000
```

## Workspace Model

Projects live inside:

```text
workspace/
```

This is intentionally web-based like Google Colab/Jupyter-style workspaces. Users select a workspace from the top bar instead of browsing the whole local machine.

## Next Phase

Phase 4 will connect the Bob Assistant panel to backend APIs for:

- Explain current file
- Fix errors
- Generate Flask route
- Add HTML form
- Preview patch
- Apply patch
