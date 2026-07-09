# Bob IDE

Bob IDE is a local VS Code-style environment built with React, Monaco, a Node
application gateway, and a Python MCP service. Python remains the authority
for workspace operations, JSON source control, validation, Bob model runs, and
the Colab handoff.

## Architecture

```text
React + Monaco (:5173 in development)
  -> Node Express + Socket.IO (:3000)
  -> MCP Streamable HTTP
  -> Python FastMCP (:8001/mcp)
  -> capabilities.py
  -> bob_core and Colab
```

Node serves the production frontend and owns filesystem watching, realtime
events, terminal PTYs, and the Pyright LSP bridge. Every frontend command uses
`POST /api/mcp/call`; Node discovers and invokes Python tools through the
official MCP SDK.

## Install

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
npm.cmd install
npm.cmd --prefix frontend install
```

## Development

Start all three services:

```powershell
npm.cmd run dev
```

Open `http://127.0.0.1:5173`.

They can also be started separately:

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

Open `http://127.0.0.1:3000`. Node serves `frontend/dist` and returns an
actionable error when the frontend has not been built.

## Verification

```powershell
npm.cmd test
```

The suite runs Python tests, Node tests, the React-to-MCP contract check,
frontend lint, and the production build.

Health and tool discovery:

```powershell
Invoke-RestMethod http://127.0.0.1:3000/api/health
Invoke-RestMethod http://127.0.0.1:3000/api/mcp/tools
```

## Runtime Configuration

Node configuration is stored in `data/node-config.json`. Environment
variables override stored values:

- `BOB_HOST`
- `BOB_PORT`
- `BOB_MCP_URL`
- `BOB_WORKSPACE_ROOT`
- `BOB_FRONTEND_DIST`

Colab and model configuration remains in Python and is managed through
`model.get_config`, `model.set_config`, and `model.health`.

## Security

The integrated terminal is a real local shell and is not sandboxed. All
services bind to localhost by default. Do not expose them to an untrusted
network.
