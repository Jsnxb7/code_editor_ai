const BASE = "/api";

async function request(path, options = {}) {
  const res = await fetch(`${BASE}${path}`, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  let body;
  try {
    body = await res.json();
  } catch {
    throw new Error(`Request failed (${res.status})`);
  }
  if (!res.ok || body.ok === false) {
    throw new Error(body.error || `Request failed (${res.status})`);
  }
  return body.data !== undefined ? body.data : body;
}

const invoke = (name, arguments_ = {}) =>
  request("/mcp/call", {
    method: "POST",
    body: JSON.stringify({ name, arguments: arguments_ }),
  });

export const api = {
  tools: () => request("/mcp/tools"),
  status: () => invoke("system.status"),
  workspaces: () => invoke("workspace.list"),
  createWorkspace: (name) => invoke("workspace.create", { name }),
  importWorkspace: (name, files, folders = []) =>
    invoke("workspace.import", { name, files, folders }),
  tree: (project) => invoke("workspace.tree", { project }),
  readFile: (project, path) => invoke("file.read", { project, path }),
  saveFile: (project, path, content) =>
    invoke("file.write", { project, path, content }),
  createFile: (project, path) => invoke("file.create", { project, path }),
  deleteFile: (project, path) => invoke("file.delete", { project, path }),
  renameFile: (project, path, newPath) =>
    invoke("file.rename", { project, path, new_path: newPath }),
  createFolder: (project, path) => invoke("folder.create", { project, path }),
  validate: (path, content) =>
    invoke("code.validate", { path, content }),
  runPytest: (project) => invoke("test.pytest", { project }),
  search: (project, query) => invoke("code.search", { project, query }),
  bobChat: (project, message, activePath) =>
    invoke("assistant.chat", { project, message, active_path: activePath }),
  worktreeStatus: (project) => invoke("worktree.status", { project }),
  worktreeDiff: (project, changeId) =>
    invoke("worktree.get_diff", { project, change_id: changeId }),
  worktreeStage: (project, changeId) =>
    invoke("worktree.stage_change", { project, change_id: changeId }),
  worktreeUnstage: (project, changeId) =>
    invoke("worktree.unstage_change", { project, change_id: changeId }),
  worktreeStageAll: (project) => invoke("worktree.stage_all", { project }),
  worktreeUnstageAll: (project) => invoke("worktree.unstage_all", { project }),
  worktreeStageMany: (project, changeIds) =>
    invoke("worktree.stage_many", { project, change_ids: changeIds }),
  worktreeUnstageMany: (project, changeIds) =>
    invoke("worktree.unstage_many", { project, change_ids: changeIds }),
  worktreeApply: (project, changeId) =>
    invoke("worktree.apply_change", { project, change_id: changeId }),
  worktreeApplyMany: (project, changeIds, override = false) =>
    invoke("worktree.apply_many", { project, change_ids: changeIds, override }),
  worktreeApplyAll: (project, override = false) =>
    invoke("worktree.apply_all", { project, override }),
  worktreeApplyPassing: (project) => invoke("worktree.apply_passing", { project }),
  worktreeOverrideApply: (project, changeId) =>
    invoke("worktree.override_and_apply", { project, change_id: changeId }),
  worktreeDiscard: (project, changeId) =>
    invoke("worktree.discard_change", { project, change_id: changeId }),
  worktreeDiscardMany: (project, changeIds) =>
    invoke("worktree.discard_many", { project, change_ids: changeIds }),
  worktreeDiscardAll: (project) => invoke("worktree.discard_all", { project }),
  worktreeSnapshot: (project, label) =>
    invoke("worktree.create_snapshot", { project, label, message: label }),
  worktreeHistory: (project) => invoke("worktree.history", { project }),
  worktreeFileHistory: (project, path) => invoke("worktree.file_history", { project, path }),
  worktreeTimeline: (project) => invoke("worktree.timeline", { project }),
  worktreeStageHunk: (project, changeId, hunkId) =>
    invoke("worktree.stage_hunk", { project, change_id: changeId, hunk_id: hunkId }),
  worktreeDiscardHunk: (project, changeId, hunkId) =>
    invoke("worktree.discard_hunk", { project, change_id: changeId, hunk_id: hunkId }),
  worktreeApplyHunk: (project, changeId, hunkId) =>
    invoke("worktree.apply_hunk", { project, change_id: changeId, hunk_id: hunkId }),
  worktreeApplyAllHunks: (project, changeId) =>
    invoke("worktree.apply_all_hunks", { project, change_id: changeId }),
  worktreeRestoreFile: (project, path, snapshotId) =>
    invoke("worktree.restore_file", { project, path, snapshot_id: snapshotId }),
  worktreeCompareSnapshot: (project, path, snapshotId) =>
    invoke("worktree.compare_with_snapshot", { project, path, snapshot_id: snapshotId }),
  worktreeRestoreSnapshot: (project, snapshotId) =>
    invoke("worktree.restore_snapshot", { project, snapshot_id: snapshotId }),
  worktreeIgnorePath: (project, path) => invoke("worktree.ignore_path", { project, path }),
  worktreeGenerateCheckpointMessage: (project) =>
    invoke("worktree.generate_checkpoint_message", { project }),
  modelGetConfig: () => invoke("model.get_config"),
  modelSetConfig: (config) => invoke("model.set_config", config),
  modelHealth: () => invoke("model.health"),
  modelPlan: (project, prompt, activePath) =>
    invoke("model.plan", { project, prompt, active_path: activePath }),
  modelRunAgent: (project, prompt, activePath) =>
    invoke("model.run_agent", { project, prompt, active_path: activePath }),
  modelRunStatus: (project, runId) =>
    invoke("model.run_status", { project, run_id: runId }),
};
