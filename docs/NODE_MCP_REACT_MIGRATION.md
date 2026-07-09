# Node, MCP, and React Migration

## Runtime Pipeline

1. React sends commands to Node through `/api/mcp/call`.
2. Node uses the official MCP JavaScript client.
3. Python FastMCP dispatches the selected function from `capabilities.py`.
4. Capabilities call Bob Core modules and return structured JSON.
5. Node normalizes the MCP response to `{ok, data}` for React.

Node never duplicates Python business logic.

## Python Module Coverage

| Module | MCP connection |
|---|---|
| `capabilities.py` | Registers every public tool |
| `workspace_tools.py` | Search compatibility helpers |
| `bob_core/file_manager.py` | Workspace and file/folder tools |
| `bob_core/json_worktree.py` | Source control, history, hunks, restore, runs |
| `bob_core/json_store.py` | Internal atomic storage |
| `bob_core/model_service.py` | Plan/agent run tools |
| `bob_core/model_config.py` | Model configuration tools |
| `bob_core/colab_adapter.py` | Colab plan, agent, and health calls |
| `bob_core/validator.py` | Validation tools |
| `bob_core/command_runner.py` | Python, stop, shell, and pytest tools |
| `config.py` | Shared Python paths and limits |
| `mcp_server.py` | Official MCP Streamable HTTP host |

Internal storage helpers are reached transitively and are intentionally not
exposed as unsafe low-level tools.

## Realtime

- Chokidar detects editor, terminal, and external filesystem changes.
- Mutating MCP calls invalidate the active workspace immediately.
- React calls `worktree.scan` for filesystem changes and `worktree.status`
  for indexed `.bob` state changes.
- Bob run changes are emitted from `.bob/runs.json`.
- Reconnect performs one recovery refresh; there is no continuous SCM or
  model-run polling.

## Event Compatibility

Node preserves workspace rooms, collaborative `editor:change`, all
`terminal:*` events, `model:run`, `model:config`, and the `/lsp` namespace.
The terminal uses `node-pty`; Pyright uses stdio JSON-RPC.

## Former Flask Surface

The former backend is preserved in `legacy/flask_backend` and is unsupported.
Its REST commands are replaced by generic MCP calls, and its Socket.IO,
watcher, terminal, and LSP responsibilities now belong to Node.

## Ports

- React/Vite development: `5173`
- Node application gateway: `3000`
- Python MCP: `8001`
