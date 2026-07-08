# Bob IDE

A web-based, VS Code-inspired IDE: Monaco editor, multi-tab files, a real
interactive terminal, file explorer with context menus, command palette,
quick-open, and a reserved panel for a future "Bob" coding assistant.

This version is a full rebuild of the original prototype:

- **Frontend**: rewritten from vanilla JS into **React + Vite**, structured
  like VS Code (activity bar, resizable sidebar/panel/assistant rail,
  multi-tab editor, breadcrumbs, command palette, quick-open).
- **Backend**: still **Flask**, but the terminal is now backed by a **real
  pseudo-terminal (PTY)** instead of a command-by-command request/response
  loop, streamed over Socket.IO.
- Several dead/broken wires from the original build were fixed in the
  process (see "What changed" below).

## Quick start

```bash
pip install -r requirements.txt
python app.py
```

Then open <http://127.0.0.1:5000>. The frontend is already built into
`frontend/dist/` and Flask serves it directly — no Node.js is required just
to run the app.

### Working on the frontend

If you want to change the UI, you do need Node:

```bash
cd frontend
npm install
npm run dev        # Vite dev server on :5173, proxies /api and /socket.io to Flask on :5000
```

Run `python app.py` in another terminal first so the proxy has something to
talk to. When you're done, rebuild the static bundle Flask serves:

```bash
npm run build       # writes frontend/dist — this is what app.py serves
```

## The real-time terminal

Each terminal tab in the UI is backed by an actual shell process:

- **Linux/macOS**: a real PTY via Python's stdlib `pty` module — the same
  mechanism every terminal emulator uses. Arrow-key history, Ctrl+C,
  tab-completion, `vim`, REPLs, and long-running dev servers all behave
  exactly like a normal terminal, because it *is* one.
- **Windows**: a real ConPTY session via `pywinpty` if it's installed
  (`pip install pywinpty`). Without it, the app falls back to a more
  limited line-buffered shell — output still streams live, but you lose
  local readline-style editing and signal forwarding (Ctrl+C). The fallback
  exists so the app doesn't crash on a machine without `pywinpty`; install
  it for the full experience.

Bytes flow straight between the browser (xterm.js) and the shell over
Socket.IO — there's no command parsing or allow-listing in the middle. That
also means the **Run ▶** button doesn't execute anything specially; it just
types `python <file>` into the active terminal, exactly like you would.

> **Heads up:** this gives whoever has the page open a real shell on the
> machine running the server, scoped to start in the selected workspace
> folder but not sandboxed beyond that (a real `cd ..` works, like any
> terminal). That's the point — it's a local dev tool, the same trust model
> as opening a terminal yourself. Don't expose this server to the network
> or to people you don't trust.

## Keyboard shortcuts

| Shortcut | Action |
|---|---|
| `Ctrl/Cmd + S` | Save current file |
| `Ctrl/Cmd + P` | Quick Open (fuzzy file finder) |
| `Ctrl/Cmd + Shift + P` | Command Palette |
| `Ctrl/Cmd + \`` | Toggle bottom panel (terminal/problems/search) |
| `Ctrl/Cmd + B` | Toggle sidebar |

## Project layout

```
app.py                  Flask app factory; serves frontend/dist + the API blueprint
config.py               Paths, allowed file extensions, ignored dirs
realtime.py             Socket.IO event wiring for the terminal
terminal_session.py     Cross-platform real-PTY session management
routes/api.py           REST endpoints (files, folders, validate, pytest, search)
bob_core/
  file_manager.py       Safe path resolution, tree scan, CRUD for files/folders
  validator.py          ast-based Python syntax checks, JSON checks
  command_runner.py     Headless one-shot runners (pytest summary, utility python run)
workspace_tools.py       Small helper module used by tooling/automation, not the UI
workspace/               Your projects live here, one subfolder per workspace
frontend/                React + Vite source
  src/context/IdeContext.jsx   Central app state (tabs, tree, terminals, dialogs…)
  src/components/              UI pieces (Sidebar, EditorArea, TerminalPanel, …)
  dist/                        Prebuilt static bundle Flask serves (gitignored, included in this zip)
```

## REST API

All responses are `{"ok": true, "data": ...}` or `{"ok": false, "error": "..."}`.

| Method & path | Purpose |
|---|---|
| `GET /api/status` | Whether Socket.IO is available |
| `GET /api/workspaces` | List workspace folders |
| `POST /api/workspace/create` | Create a new workspace (`{name}`) |
| `GET /api/project/tree?project=` | File tree for a workspace |
| `GET /api/file/read?project=&path=` | Read a file |
| `POST /api/file/save` | Save a file (`{project, path, content}`) |
| `POST /api/file/create` | Create an empty file |
| `POST /api/file/delete` | Delete a file or folder (recursively) |
| `POST /api/file/rename` | Rename/move a file or folder |
| `POST /api/folder/create` | Create a folder |
| `POST /api/validate` | `ast`/JSON syntax check (`{path, content}`) |
| `POST /api/run/pytest` | Run pytest in a workspace, structured pass/fail summary |
| `GET /api/search?project=&q=` | Plain-text search across workspace files |

Socket.IO events are documented at the top of `realtime.py`.

## What changed from the original prototype

- The original `static/js/ide.js` referenced a `commandBtn`/`commandInput`
  pair that didn't exist in `templates/index.html` — calling `.onclick` on
  the missing element threw and silently broke every script wired up after
  it (tab switching, search). That whole vanilla-JS layer is replaced.
- The terminal used to run one buffered command at a time over
  Flask/PowerShell, with no live streaming and no support for interactive
  programs. It's now a real PTY streamed continuously over Socket.IO.
- Folder rename/delete didn't exist (only files could be renamed/deleted);
  both now work for files and folders.
- Duplicate/dead HTTP routes (`/api/run`, `/api/run/command`, `/api/run/stop`,
  a second copy of file read/save under different paths) were removed in
  favor of one consistent `/api/file/*`, `/api/folder/*` surface — running
  and stopping things now happens through the real terminal instead.

## Known limitations

- The "Bob Assistant" panel is intentionally a placeholder — it isn't wired
  to a backend yet (see the original roadmap: explain file, fix errors,
  generate routes, patch preview/apply). This rebuild focused on the editor,
  file management, and terminal experience.
- No authentication — this is a local single-user dev tool.
- `pytest` must be installed in whatever Python environment runs `app.py`
  for the **Tests** button to do anything; if it's missing, the Problems
  panel will say so instead of crashing.
