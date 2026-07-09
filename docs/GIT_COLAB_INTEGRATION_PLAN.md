# Real Git and Colab-Backed Bob Integration

## Summary

Replace JSON source control with isolated Git repositories while converting
Bob's existing Colab notebook into a versioned model service used by Bob Chat
through MCP.

```text
React Bob Chat / Source Control
  -> Node gateway + realtime
  -> Python MCP
       -> git_service.py -> workspace/.git
       -> proposal_store.py -> workspace/.bob/proposals
       -> model_service.py -> Colab notebook HTTP service
```

Git owns source control. Bob owns proposals and model-run records. Colab never
writes workspace files.

## Git Source Control

- Add `git_service.py`; require each workspace's Git top-level to equal its own
  directory so the parent Bob IDE repository is never used.
- Auto-initialize new/imported workspaces on `main`, without an initial commit.
- Implement status, index/working/HEAD diffs, stage, unstage, hunks, discard,
  commits, identity, branches, history, restore, and three-way conflicts.
- Use porcelain-v2 status and `subprocess.run(..., shell=False)`.
- Preserve confirmations for destructive actions and reject unsafe branch
  switching.
- Add `git.*` MCP tools and keep `worktree.*` compatibility aliases for one
  release.
- Replace checkpoints with commits, `.bobignore` with `.gitignore`, and JSON
  history views with Git log/file history.

## Bob Proposal Store

Add `proposal_store.py` with grouped, run-linked proposals under
`.bob/proposals`.

Store:

- `proposal_id`, `run_id`, summary, risk, review status, and lifecycle state.
- Before/after blobs, patches, hashes, action, and `base_git_head`.
- Per-file and hunk state.
- States: proposed, applied, discarded, conflict, failed-review, superseded.

Capabilities:

- `proposal.list`, `proposal.status`, `proposal.diff`
- `proposal.apply`, `proposal.override_apply`, `proposal.apply_hunk`
- `proposal.apply_all`, `proposal.discard`, `proposal.discard_all`

Applying checks the current file hash before writing. Successful application
changes the workspace only; Git then reports a normal unstaged change.

## Existing JSON Migration

Implement an idempotent migration with rollback:

1. Back up legacy state under `.bob/legacy-json-worktree/<timestamp>`.
2. Convert every historical snapshot into an ordered Git commit using a
   temporary index.
3. Preserve messages and timestamps without touching workspace files.
4. Point `main` to the latest migrated checkpoint.
5. Reconstruct staged files and partial-hunk index content.
6. Leave current files unchanged so Git detects remaining manual edits.
7. Group and migrate active Bob proposals by model run.
8. Preserve runs and model-stage records.
9. Verify commit trees, index contents, proposals, and workspace hashes.
10. Mark migration complete only after every verification passes.

Migration commits use a temporary `Bob IDE Migration <bob@localhost>` identity.
Normal commits require user-configured repository or global identity.

## Colab Notebook Contract

Update `Untitled28_colab_bob_ide_http_standalone_showcase.ipynb` to expose a
versioned `bob-colab-v2` service.

Endpoints:

- `GET /health`: availability, model name, GPU state, loaded state, and
  contract version.
- `GET /capabilities`: supported endpoints, modes, limits, streaming,
  cancellation, and response schemas.
- `POST /chat`: conversational response without proposals.
- `POST /plan`: normalized structured plan.
- `POST /run-agent`: synchronous planner -> context -> coder -> reviewer.
- `POST /run-agent/stream`: SSE stage events and final result.
- `GET /runs/<run_id>`: Colab-side recovery status.
- `POST /runs/<run_id>/cancel`: cooperative cancellation between stages and
  iterations.

Notebook rules:

- Accept workspace tree, selected context files, active path, Git branch/HEAD,
  prompt, run ID, context mode, context budget, and maximum iterations.
- Return full generated file contents or `null` for deletion.
- Include plan, code, review, final status, provider, model, timings, and
  proposal metadata.
- Never write Bob IDE workspace files.
- Preserve the shared-model behavior and keep it loaded by default.
- Check cancellation between planner iterations, context building, coding,
  and review.
- Emit SSE events: queued, planning, context, coding, reviewing, completed,
  failed, cancelled.
- Keep Hugging Face and ngrok secrets inside Colab; never send them to Bob IDE.
- Continue supporting bearer authentication through `BOB_COLAB_TOKEN`.

## Bob Chat Connection UI

Expand the existing Model Connection section with:

- Colab/ngrok base URL.
- Health path and capabilities path.
- Chat, plan, synchronous run, streaming run, run-status, and cancel paths.
- Timeout.
- Bearer token with masked replacement/clear behavior.
- Extra headers JSON.
- Maximum planner iterations.
- Context mode: active file, open files, or workspace.
- Context byte budget.
- Prefer streaming toggle, enabled by default.
- Keep model loaded toggle, enabled by default.

After Test Connection:

- Fetch `/health` and `/capabilities`.
- Display model, contract version, GPU/runtime status, loaded state, supported
  modes, streaming, and limits.
- Reject incompatible contracts before starting runs.
- Never display or request Hugging Face or ngrok authentication secrets.

Keep Chat, Plan, and Run as the primary segmented modes:

- Chat calls the notebook `/chat` endpoint through `model.chat`.
- Plan calls `/plan` and renders structured plan fields.
- Run queues an asynchronous local run and uses streaming when available.
- Run cards display live stage, elapsed time, plan, review, generated
  proposals, errors, and cancellation.
- Completed proposals link directly to Source Control and Monaco proposal
  diffs.

## Model and MCP Layer

Extend model configuration with:

- `health_path`, `capabilities_path`, `chat_path`
- `plan_path`, `run_path`, `stream_path`
- `run_status_path`, `cancel_path`
- `max_iterations`, `context_mode`, `context_budget`
- `prefer_streaming`, `keep_model_loaded`
- Existing URL, token, timeout, and headers

Add MCP tools:

- `model.get_config`, `model.set_config`
- `model.health`, `model.capabilities`
- `model.chat`, `model.plan`, `model.run_agent`
- `model.run_status`, `model.cancel_run`
- `model.list_runs`, `model.get_run_stages`

`model_service.py` will:

1. Build context according to the selected mode and budget.
2. Include Git branch and HEAD metadata.
3. Start a persisted local run.
4. Consume Colab SSE events when supported, otherwise use synchronous HTTP.
5. Persist every stage and update `.bob/runs.json`.
6. Create proposal-store records from returned files.
7. Link `proposal_ids` and paths to the run.
8. Never invoke `file.write` for model output.

Node watches run/proposal records and emits `model:run` and
`proposal:changed`, allowing Bob Chat to update without polling.

## React Source Control

Provide VS Code-style sections:

- Proposed by Bob
- Merge Changes
- Changes
- Untracked
- Staged Changes
- Git History
- Bob Runs

Diff sources:

- Unstaged: index -> working tree.
- Staged: HEAD -> index.
- Untracked: empty -> working tree.
- Proposal: stored before -> proposed after.
- Conflict: Git base/current/incoming.

Retain hunk operations, Explorer/tab decorations, history, timeline, filtering,
sorting, batch actions, and status badges.

External changes never overwrite open tabs. Dirty or clean open files receive
a changed-on-disk state with Compare, Reload, or Keep Editor Content.

## Realtime

Node watches:

- Workspace files.
- `.git/index`, HEAD, refs, merge/rebase state.
- `.bob/proposals` metadata.
- Runs and model-stage records.

Events:

- `source-control:changed`
- `git:changed`
- `proposal:changed`
- `model:run`
- Compatibility `worktree:changed`

React refreshes authoritative Git/proposal state after events; no continuous
polling.

## Test Plan

- Git boundary, init, unborn branch, status, diff, staging, hunks, commits,
  branches, restore, identity, conflicts, and destructive-operation tests.
- Proposal create, grouping, diff, hunk apply, conflict, override, discard,
  and model-link tests.
- Migration tests for multiple snapshots, partial staging, proposals,
  timestamps, rollback, and unchanged workspace hashes.
- Notebook contract tests for health, capabilities, auth, chat, plan, sync
  run, stream events, cancellation, malformed responses, and proposal-only
  output.
- Model adapter tests for context budgets, Git metadata, streaming fallback,
  reconnect recovery, persisted stages, and proposal creation.
- MCP contract tests covering every React API method.
- Node watcher/event tests for Git, proposals, and model stages.
- Browser smoke: connect Colab, chat, plan, run, watch stages, review proposal,
  apply, stage, commit, branch, and conflict handling.
- Run Python, Node, API-contract, frontend lint/build, and live MCP/PTY/LSP
  tests.

## Assumptions

- Every workspace owns an isolated nested Git repository.
- Existing JSON history and proposals are preserved.
- New/imported workspaces auto-initialize without an initial commit.
- Streaming is preferred with synchronous fallback.
- The notebook remains a Colab-hosted Flask service exposed through ngrok or
  another tunnel.
- Local Git ships first; remotes and push/pull remain a later phase.
- Legacy `worktree.*` aliases remain for one release before removal.
