# Bob IDE

Bob IDE is a local VS Code-style coding environment with a React + Monaco editor, a Node gateway, a Python MCP tool service, Git-style source control, and a Colab-powered Bob coding assistant.

The app is split into four parts:

```text
React + Monaco frontend
  -> Node Express + Socket.IO gateway
  -> Python MCP service
  -> Bob Core tools + Colab model server
```

Use the React app for the IDE, Node for the app server and realtime layer, Python MCP for workspace/file/model tools, and Colab for the large model runtime.

---

## Main features

- VS Code-like layout with Explorer, editor tabs, Bob chat, Source Control, terminal, search, and status bar.
- Monaco editor and Monaco diff viewer.
- Node gateway for frontend API, Socket.IO realtime events, terminal, and production React serving.
- Python MCP service for workspace operations, file operations, validation, Git/source-control tools, Bob model calls, proposals, and context building.
- Bob chat staged workflow:
  - Plan
  - Replan
  - Code selected plan
  - Review
  - Run all
- Forced context files for Bob:
  - active file
  - open tabs
  - manually picked files
- Bob proposals are stored locally first and are not written to real project files until accepted.
- Source Control shows proposed Bob changes separately from real Git/project changes.
- Colab model server with ngrok exposure.
- Standalone Colab showcase mode for running the model without the IDE.

---

## Multi-user runtime model

- Authentication sessions, CSRF tokens, workspace ownership, Socket.IO rooms, PTYs, and Pyright processes are bound to the authenticated user. Physical projects live at `workspace/<username>--<user-id>/<project>`; only the final project name is exposed to the frontend.
- The authenticated Node gateway converts every public project name to the caller's physical project reference before calling MCP. This permits different users to use the same project name without sharing files, events, terminals, LSP state, or ownership records.
- Every terminal, including an admin terminal, fails closed unless `BOB_TERMINAL_SANDBOX_IMAGE` is set. When configured, Docker bind-mounts only the authenticated user's project bundle at `/workspace`; sibling users and host parent directories are not mounted. The terminal starts in the IDE's active project, follows project changes, permits navigation among that user's projects, and rejects attempts to `cd` above the user root. The prompt shows only virtual paths such as `bob:/project-a/src`. The image includes `python`, `python3`, `pip`, and `venv`; the container also uses a read-only system root, no network, dropped capabilities, CPU/memory/PID limits, and `no-new-privileges`.
- Non-admin `terminal.execute`, `code.run_python`, and `test.pytest` MCP calls are denied because they would otherwise execute under the shared host account. Run those commands through the container terminal, or move them to the same container worker design before enabling them.
- All model-generating MCP tools (`model.chat`, plan/replan, code, direct code, review, and run-all) share one fair in-process lane. Waiting work alternates between users when possible. `model.queue_status` exposes only the caller's job details.
- `model.code_direct` skips planning but still executes the mandatory reviewer before returning a proposal. `model.run_agent` remains planner → coder → reviewer.
- Keep Python MCP bound to `127.0.0.1` or a private container network and expose only the authenticated Node gateway. Direct public MCP access would bypass the gateway's user/workspace authorization.
- Run exactly one Python MCP process while using the in-process single lane. If MCP is horizontally scaled, replace the in-memory lane with a shared Redis/SQS-backed worker queue before adding replicas.
- Directory scoping is application isolation; the Docker terminal is the hostile-command boundary. Do not grant users the host shell or mount the Docker socket inside their terminal container.

---

## Structured runtime logs

Bob writes secret-redacted, rotating JSONL logs for the application, model pipeline, and ngrok transport. Logs contain request/trace/run IDs, stages, status, attempts, latency, usage, sizes, and errors; they do not contain prompt text, generated code, workspace contents, credentials, cookies, or authorization headers.

Local IDE logs are stored in:

```text
data/runtime/events.jsonl          App, API, Socket.IO, terminal, tool, auth, and audit events
data/runtime/model-events.jsonl    Model run and stage events
data/runtime/ngrok-events.jsonl    Colab/ngrok request, response, retry, and error events
```

Each file rotates at approximately 10 MB to a `.1` backup. An authenticated Admin can query one stream with `/api/dev/logs?source=app|model|ngrok`, or correlate all streams with `/api/dev/logs?source=all&trace_id=<trace-id>`. The same endpoint supports `request_id`, `run_id`, `actor_user_id`, `type`/`event`, and `limit` filters.

The verified Lightning/Colab notebook writes its remote runtime logs to `bob_runtime_logs/` by default. Set `BOB_RUNTIME_LOG_DIR` before running the contract/start cells to choose another persistent mounted directory. The notebook prints the resolved location when it starts.

The updated `Untitled28_lightning_ai_bob_runtime (1).ipynb` has a Phase 0.2A switch for `single` or `multi` runtime mode and defaults to the production-safe single lane. Set `BOB_RUNTIME_MODE=multi` and optionally `BOB_MULTI_LANE_COUNT=2` or `3` before running the notebook to override it for a larger GPU. `BOB_PRELOAD_MODEL_LANES=1` (the default) loads exactly the configured number of replicas sequentially before Flask starts; use `0` only for deliberate lazy loading. Restart the kernel before changing modes. Every core cell is tagged as compatible with both modes, while mode-sensitive startup cells are labeled explicitly. In multi mode, each request must retain the same `pipeline_id` and `model_lane` through its stages.

---

## Three-approach live evaluation

The unified evaluation contains 74 unchanged as-is prompts, 74 paired naturalized rewrites, and 30 new natural-user prompts. Every prompt variant is evaluated with direct coder + model reviewer, the same direct coder response + a blind thresholded evaluator, and the complete planner + coder + reviewer pipeline.

```powershell
$env:BOB_PYTHON="C:\path\to\python.exe"
$env:BOB_ALLOW_LIVE_EVAL="1"
$env:BOB_COLAB_BASE_URL="https://your-ngrok-runtime"
$env:BOB_COLAB_TOKEN="your-runtime-token"

npm run eval:three:prepare
node scripts/run-python.mjs scripts/run_three_approach_live_evals.py --limit-cases 178 --concurrency 3
npm run eval:three:artifacts
npm run eval:consolidate
npm run eval:verify
```

The live runner uses one sequential queue per remote model lane. A lane never overlaps two pipelines, while the three independent lanes run concurrently. Checkpoint writes are lock-protected and atomic, and every record carries `evaluation_run_id`, `pipeline_id`, `model_lane`, case/test ID, approach, stage, request ID and trace ID. Successful call keys resume without repetition. Its restricted master JSON contains prompts, generated code, reviews and test evidence; the operational JSONL logs contain identifiers, hashes and sizes instead of prompt or code contents.

The canonical case catalog is `evals/consolidated_cases.json`. It contains the 12 offline cases, historical endpoint suites, 74 source requirements, 178 current prompt variants and their source/reference metadata. New live runs use `output/evals/consolidated/run-workspace/` as their temporary checkpoint and artifact directory.

The accepted evaluation history is stored in only two output JSON files: `output/evals/consolidated/consolidated_evaluation.json` contains all accepted historical runs and analysis, while `output/evals/consolidated/consolidated_verification.json` contains source hashes, backup metadata, integrity checks and cleanup provenance. The nine-page chart book is `output/pdf/consolidated-evaluation-charts.pdf`. Operational app, model and ngrok logs remain separate JSONL files under `data/runtime/` and are not duplicated into the evidence master.

The lossless pre-consolidation recovery archive is `output/archive/evaluation-history-preconsolidation-20260810.zip`. It contains all 247 imported source files and can reconstruct the retired per-run directories; its SHA-256 is recorded in the consolidated verification JSON.

To freeze a stopped live run without making network calls, use `node scripts/run-python.mjs scripts/run_three_approach_live_evals.py --snapshot-only`. After a completed run, build its temporary artifacts, import them into the consolidated history, and run `npm run eval:verify` before removing the temporary workspace.

---

## Folder layout

```text
bob-ide/
  bob_core/              Python business logic and tools
  capabilities.py        Python MCP capability registry
  mcp_server.py          Python FastMCP server
  node-server/           Node Express + Socket.IO gateway
  frontend/              React + Monaco frontend
  scripts/               Helper scripts and verification scripts
  docs/                  Detailed architecture docs
  workspace/             Local workspaces/projects
  data/                  Node config and local runtime data
  legacy/                Old Flask backend archive
  README.md              This file
```

---

## Ports used

```text
Python MCP service: 127.0.0.1:8001
Node gateway:       127.0.0.1:3000
React dev server:   127.0.0.1:5173
Colab HTTP server:  8000 inside Colab, exposed by ngrok
```

In development, open:

```text
http://127.0.0.1:5173
```

In production, open:

```text
http://127.0.0.1:3000
```

---

# Part 1: Install required software

## 1. Install Python

Install Python 3.10 or newer.

Check Python:

```powershell
python --version
```

If that does not work, try:

```powershell
py --version
```

## 2. Install Node.js

Install Node.js LTS from the official Node.js website.

Check Node and npm:

```powershell
node --version
npm --version
```

## 3. Install Git

Install Git for Windows.

Check Git:

```powershell
git --version
```

## 4. Install Visual Studio Build Tools if needed

The root Node server uses `node-pty` for the integrated terminal. On Windows, `node-pty` may need build tools.

If `npm install` fails while installing `node-pty`, install:

```text
Visual Studio Build Tools
Desktop development with C++
Windows SDK
```

Then reopen PowerShell and run `npm install` again.

---

# Part 2: Extract the project

Extract the project zip somewhere simple, for example:

```text
C:\Users\shour\Documents\GitHub\code_editor_ai
```

Open PowerShell in the extracted project folder.

Example:

```powershell
cd C:\Users\shour\Documents\GitHub\code_editor_ai
```

---

# Part 3: Create and activate Python virtual environment

Create the virtual environment:

```powershell
python -m venv .venv
```

Activate it:

```powershell
.\.venv\Scripts\activate
```

Your terminal should now show `(.venv)`.

Install Python dependencies:

```powershell
python -m pip install --upgrade pip
pip install -r requirements.txt
```

The minimum required dependency is the MCP SDK:

```text
mcp[cli]
```

If extra Python packages are added later, they should also go into `requirements.txt`.

---

# Part 4: Install Node dependencies

From the project root, install Node gateway dependencies:

```powershell
npm install
```

Install frontend dependencies:

```powershell
npm --prefix frontend install
```

If PowerShell blocks npm scripts, run:

```powershell
Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
```

Then close and reopen PowerShell.

Alternative without changing the policy:

```powershell
cmd /c npm install
cmd /c npm --prefix frontend install
```

---

# Part 5: Run the app in development mode

The development app uses three services:

```text
Python MCP service
Node gateway
React dev server
```

## Option A: Start everything with one command

From the project root:

```powershell
npm run dev
```

Then open:

```text
http://127.0.0.1:5173
```

## Option B: Start each service manually

Open three PowerShell terminals in the project root.

### Terminal 1: Python MCP service

```powershell
.\.venv\Scripts\activate
npm run dev:python
```

This starts Python MCP on:

```text
http://127.0.0.1:8001/mcp
```

### Terminal 2: Node gateway

```powershell
npm run dev:node
```

This starts Node on:

```text
http://127.0.0.1:3000
```

### Terminal 3: React frontend

```powershell
npm run dev:frontend
```

This starts React on:

```text
http://127.0.0.1:5173
```

Open the browser at:

```text
http://127.0.0.1:5173
```

---

# Part 6: Run the app in production mode

Build the React frontend:

```powershell
npm run build
```

Start Python MCP:

```powershell
npm run dev:python
```

In a second terminal, start Node production server:

```powershell
npm start
```

Open:

```text
http://127.0.0.1:3000
```

In production mode, Node serves the built React files from `frontend/dist`.

---

# Part 7: Verify local services

Check Node health:

```powershell
Invoke-RestMethod http://127.0.0.1:3000/api/health
```

Check MCP tools through Node:

```powershell
Invoke-RestMethod http://127.0.0.1:3000/api/mcp/tools
```

Run tests:

```powershell
npm test
```

This runs:

```text
Python tests
Node tests
API contract tests
Frontend lint
Frontend production build
```

---

# Part 8: Open the Colab notebook

Use this Colab notebook:

[Open the Bob IDE Colab notebook](https://colab.research.google.com/drive/1Uddwha_w4uxxFPWDO4SopG0b8NiiOJyo?usp=sharing)

Open the notebook in Google Colab.

Set runtime to GPU:

```text
Runtime -> Change runtime type -> GPU
```

Then run the setup cells from the top.

---

# Part 9: Add Hugging Face token in Colab

Some models may need a Hugging Face token. Even if the selected model is public, setting the token avoids many download/auth problems.

## 1. Get Hugging Face token

Go to your Hugging Face account settings and create an access token.

## 2. Set token in Colab

In the notebook, find the token/setup cell and set:

```python
HF_TOKEN = "paste_your_huggingface_token_here"
```

Then login:

```python
from huggingface_hub import login
login(token=HF_TOKEN)
```

If the notebook already has a helper cell for Hugging Face login, paste the token there and run that cell.

Do not commit real tokens into Git.

---

# Part 10: Add ngrok token in Colab

ngrok exposes the Colab server to your local Bob IDE.

## 1. Get ngrok token

Create an ngrok account and copy your auth token from the ngrok dashboard.

## 2. Set token in Colab

In the notebook, set:

```python
NGROK_AUTHTOKEN = "paste_your_ngrok_token_here"
```

Then run:

```python
from pyngrok import ngrok
ngrok.set_auth_token(NGROK_AUTHTOKEN)
```

If `pyngrok` is missing, run:

```python
!pip install -q pyngrok
```

---

# Part 11: Start the Colab HTTP server

After the model/setup cells are ready, start the Colab HTTP server:

```python
server_info = start_colab_http_server(
    port=8000,
    use_ngrok=True
)

server_info
```

Expected output:

```python
{
  "port": 8000,
  "public_url": "https://xxxx-xxxx-xxxx.ngrok-free.app"
}
```

If `public_url` is `None`, restart ngrok:

```python
from pyngrok import ngrok
ngrok.kill()
ngrok.set_auth_token(NGROK_AUTHTOKEN)
public_tunnel = ngrok.connect(8000, "http")
print(public_tunnel.public_url)
```

Use the printed URL as the Base URL in Bob Chat.

Important:

```text
Do not add :8000 to the ngrok URL.
```

Correct:

```text
https://xxxx-xxxx-xxxx.ngrok-free.app
```

Wrong:

```text
https://xxxx-xxxx-xxxx.ngrok-free.app:8000
```

---

# Part 12: Test the Colab server

In Colab:

```python
import requests

base_url = server_info["public_url"]
print(requests.get(base_url + "/health").json())
print(requests.get(base_url + "/capabilities").json())
```

Expected health response:

```json
{
  "ok": true,
  "service": "bob-colab"
}
```

Available Colab routes:

```text
GET  /health
GET  /capabilities
POST /plan
POST /replan
POST /code
POST /review
POST /run-agent
POST /run-agent/stream
```

---

# Part 13: Connect Bob Chat to Colab

Open the Bob IDE in your browser.

Go to the Bob panel.

Open the Config tab.

Fill these fields:

```text
Base URL:          https://xxxx-xxxx-xxxx.ngrok-free.app
Health path:       /health
Capabilities path: /capabilities
Plan path:         /plan
Replan path:       /replan
Code path:         /code
Review path:       /review
Run path:          /run-agent
Stream path:       /run-agent/stream
Bearer token:      leave empty unless you set BOB_COLAB_TOKEN
```

Click:

```text
Save Config
```

Then click:

```text
Test Health
```

If the test succeeds, Bob IDE can reach Colab.

---

# Part 14: Optional bearer token between Bob IDE and Colab

If you want Colab to require a token, set this in the notebook before starting the server:

```python
BOB_COLAB_TOKEN = "my-secret-token"
```

Then in Bob Chat Config, set:

```text
Bearer token: my-secret-token
```

If you leave `BOB_COLAB_TOKEN` empty, leave Bearer token empty in the app.

---

# Part 15: Bob staged workflow

Bob uses a staged workflow so model changes are reviewable before they touch real files.

## Step 1: Add context files

Open the Bob panel.

Go to the Context tab.

Use:

```text
Add active file
Add open tabs
Pick file
Clear
```

Forced context files are sent as text content, not just file paths.

## Step 2: Ask for a plan

Go to the Chat tab.

Type a request, for example:

```text
Add a login page and connect it to the existing routes.
```

Click:

```text
Plan
```

Bob sends the prompt, workspace tree, active file, and forced context to Colab.

The plan is saved in:

```text
workspace/<project>/.bob/plans.json
workspace/<project>/.bob/model_runs.json
```

## Step 3: Select a plan

Go to the Plans tab.

You will see plan cards like:

```text
plan_000001
summary
files needed
files to modify
files to create
confidence
```

Click:

```text
Select Plan
```

## Step 4: Replan if needed

If Bob missed important files:

```text
1. Add files in the Context tab.
2. Go back to Plans.
3. Click Replan with Context.
```

This creates a new indexed plan such as:

```text
plan_000002
```

You can select the newer plan or go back to an older plan.

## Step 5: Send selected plan to coder

After selecting the plan, click:

```text
Code Selected Plan
```

Bob sends the selected plan and latest forced context to Colab.

The coder returns generated file contents.

## Step 6: Review

Click:

```text
Review
```

The reviewer checks the generated files and returns:

```text
PASS
```

or:

```text
FAIL
```

## Step 7: Proposal cache

Generated files are saved locally first as proposals:

```text
workspace/<project>/.bob/proposals/
```

They are not written to actual workspace files yet.

## Step 8: Preview changes

Open Source Control.

Look under:

```text
Proposed by Bob
```

Click a proposed file to open a Monaco diff.

The diff shows:

```text
left: current real file
right: proposed Bob file
```

## Step 9: Accept or reject

If the proposal is good, click:

```text
Apply
```

This writes the proposal into the real workspace file.

Then Git/source control will show it as a normal modified file.

If the proposal is not good, click:

```text
Discard
```

Discarding a Bob proposal does not touch real project files.

---

# Part 16: Source Control behavior

Bob IDE separates two things:

```text
Bob proposals
Real Git/project changes
```

Source Control groups:

```text
Proposed by Bob
Changes
Staged Changes
Merge Changes
```

Bob proposals come from:

```text
.bob/proposals
```

Real changes come from Git/project files.

A Bob proposal becomes a real source-control change only after clicking Apply.

---

# Part 17: Git setup for workspaces

For best results, initialize Git inside each workspace.

Open a terminal inside a workspace folder:

```powershell
cd workspace\sample_project
git init
git add .
git commit -m "Initial commit"
```

After that, Bob IDE can show modified files, staged files, commits, and diffs more reliably.

If Git is not initialized, some source-control features may be limited.

---

# Part 18: Common commands

## Start everything for development

```powershell
npm run dev
```

## Start only Python MCP

```powershell
npm run dev:python
```

## Start only Node gateway

```powershell
npm run dev:node
```

## Start only React frontend

```powershell
npm run dev:frontend
```

## Build frontend

```powershell
npm run build
```

## Start production server

```powershell
npm start
```

## Run all tests

```powershell
npm test
```

## Run only frontend build

```powershell
npm --prefix frontend run build
```

## Run only frontend lint

```powershell
npm --prefix frontend run lint
```

---

# Part 19: Troubleshooting

## npm is blocked in PowerShell

Run:

```powershell
Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
```

Then reopen PowerShell.

Or use:

```powershell
cmd /c npm run dev
```

## node-pty fails during npm install

Install Visual Studio Build Tools with C++ desktop workload, then run:

```powershell
npm install
```

## React opens but API calls fail

Make sure Node is running:

```powershell
npm run dev:node
```

Check:

```powershell
Invoke-RestMethod http://127.0.0.1:3000/api/health
```

## Node says Python MCP is not reachable

Start Python MCP:

```powershell
npm run dev:python
```

Then restart Node:

```powershell
npm run dev:node
```

## Bob cannot reach Colab

Check the Bob Config tab:

```text
Base URL must be the ngrok URL without :8000.
```

Test in PowerShell:

```powershell
Invoke-RestMethod https://xxxx-xxxx-xxxx.ngrok-free.app/health
```

## Colab public URL is None

In Colab:

```python
from pyngrok import ngrok
ngrok.kill()
ngrok.set_auth_token(NGROK_AUTHTOKEN)
public_tunnel = ngrok.connect(8000, "http")
print(public_tunnel.public_url)
```

Paste the printed URL into Bob Config.

## Forced context says access denied

Use the latest app files. Forced context is now read through the app and sent as text content.

Try:

```text
1. Open the file in the editor.
2. Click Add active file.
3. Or use Pick file from the Context tab.
```

## Bob proposals do not show in Source Control

Check that the project has a `.bob/proposals` folder after a coder/reviewer run.

Then refresh Source Control.

## Changes are not showing in Git

Make sure the workspace is a Git repo:

```powershell
cd workspace\your_project
git status
```

If not initialized:

```powershell
git init
git add .
git commit -m "Initial commit"
```

---

# Part 20: Safe token handling

Do not commit tokens into the project.

Do not put real tokens into README files, docs, or screenshots.

Use placeholders like:

```text
paste_your_huggingface_token_here
paste_your_ngrok_token_here
```

For local app config, use the Bob Config tab or local environment variables.

For Colab, paste tokens into notebook runtime cells only.

---

# Part 21: Recommended daily run order

Use this order:

```text
1. Open Colab notebook.
2. Set runtime to GPU.
3. Run setup/model cells.
4. Set Hugging Face token if needed.
5. Set ngrok token.
6. Start Colab HTTP server.
7. Copy ngrok URL.
8. Start local Bob IDE with npm run dev.
9. Open http://127.0.0.1:5173.
10. Paste ngrok URL into Bob Config.
11. Save config.
12. Test health.
13. Start planning/coding/reviewing.
```

---

# Part 22: Useful docs

More detailed design documents are in:

```text
docs/
```

Important files:

```text
docs/COLAB_MCP_HANDOFF.md
docs/NODE_MCP_REACT_MIGRATION.md
docs/GIT_COLAB_INTEGRATION_PLAN.md
docs/STAGED_BOB_PLAN_PROPOSAL_FLOW.md
```
