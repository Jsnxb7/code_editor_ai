# Bob IDE Continuation Handoff

## Current Architecture

- React/Vite and Monaco live in `frontend/`.
- Node gateway: `node-server/start.js`, port `3000`.
- Python FastMCP service: `mcp_server.py`, port `8001`, endpoint `/mcp`.
- Node calls every Python operation through the official MCP SDK.
- Chokidar, Socket.IO, `node-pty`, and Pyright realtime services are in Node.
- Python remains authoritative for Bob Core, Colab, validation, commands, and
  JSON source control.
- The former web backend is archived under `legacy/flask_backend/`.

See `docs/NODE_MCP_REACT_MIGRATION.md` for module and event coverage.

## Install

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
npm.cmd install
npm.cmd --prefix frontend install
```

If a virtual environment is unavailable, set `BOB_PYTHON` to a Python 3
executable before using the npm scripts.

## Development

```powershell
npm.cmd run dev
```

Open `http://127.0.0.1:5173`.

Individual services:

```powershell
npm.cmd run dev:python
npm.cmd run dev:node
npm.cmd run dev:frontend
```

## Production

```powershell
npm.cmd run build
npm.cmd run dev:python
npm.cmd start
```

Open `http://127.0.0.1:3000`.

## Verification

```powershell
npm.cmd test
npm.cmd run test:live
```

`test:live` expects Python MCP and Node to be running. It verifies React
serving, MCP discovery/calls, the real PTY, and Pyright.

## Source Control Status

Implemented:

- V1 grouped changes, staging, proposals, checkpoints, decorations, and
  realtime invalidation.
- Phase 2 hunk-level staging, discarding, proposal application, and conflicts.
- Phase 3 history, timeline, restore, ignore rules, and large/binary fallbacks.

Remaining roadmap:

1. Phase 4: safety snapshots and validation pipelines.
2. Phase 5: JSON worktree branching.
3. Phase 6: command palette and context-menu completeness.
4. Phase 7: model-backed SCM explain/review/revise/rebase.
5. Phase 8: real Git staging, commits, and worktrees.

## Colab

Configure the model URL and paths in Bob Chat. React invokes
`model.set_config` through Node and MCP; Python stores the configuration.
The intended Colab endpoints remain `/health`, `/plan`, and `/run-agent`.
