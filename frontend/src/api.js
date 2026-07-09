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
  deleteFolder: (project, path) => invoke("folder.delete", { project, path }),
  renameFolder: (project, path, newPath) =>
    invoke("folder.rename", { project, path, new_path: newPath }),
  listFiles: (project) => invoke("workspace.list_files", { project }),
  validate: (path, content) =>
    invoke("code.validate", { path, content }),
  runPytest: (project) => invoke("test.pytest", { project }),
  runPython: (project, path, timeout = 15) =>
    invoke("code.run_python", { project, path, timeout }),
  stopPython: (project, path) => invoke("code.stop_python", { project, path }),
  search: (project, query) => invoke("code.search", { project, query }),
  bobChat: (project, message, activePath) =>
    invoke("model.chat", { project, message, active_path: activePath }),
  contextBuild: (project, prompt, activePath, forcedPaths = [], openPaths = [], planId = null, maxBytes = null, forcedFiles = {}) =>
    invoke("context.build", { project, prompt, active_path: activePath, forced_paths: forcedPaths, open_paths: openPaths, plan_id: planId, max_bytes: maxBytes, forced_files: forcedFiles }),
  plansList: (project, includeInactive = true, runId = null) =>
    invoke("plans.list", { project, include_inactive: includeInactive, run_id: runId }),
  plansGet: (project, planId) => invoke("plans.get", { project, plan_id: planId }),
  plansSelect: (project, planId) => invoke("plans.select", { project, plan_id: planId }),
  plansDiscard: (project, planId) => invoke("plans.discard", { project, plan_id: planId }),

  worktreeStatus: (project) => invoke("worktree.status", { project }),
  worktreeScan: (project) => invoke("worktree.scan", { project }),
  worktreeIndexedChanges: (project) => invoke("worktree.indexed_changes", { project }),
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
  gitIsRepo: (project) => invoke("git.is_repo", { project }),
  gitInit: (project) => invoke("git.init", { project }),
  gitStatus: (project) => invoke("git.status", { project }),
  gitDiff: (project, path, staged = false, conflict = false) =>
    invoke("git.diff", { project, path, staged, conflict }),
  gitStage: (project, path) => invoke("git.stage", { project, path }),
  gitUnstage: (project, path) => invoke("git.unstage", { project, path }),
  gitStageAll: (project) => invoke("git.stage_all", { project }),
  gitUnstageAll: (project) => invoke("git.unstage_all", { project }),
  gitDiscard: (project, path, staged = false, untracked = false) =>
    invoke("git.discard", { project, path, staged, untracked }),
  gitDiscardAll: (project, includeUntracked = false) =>
    invoke("git.discard_all", { project, include_untracked: includeUntracked }),
  gitCommit: (project, message) => invoke("git.commit", { project, message }),
  gitIdentity: (project) => invoke("git.identity", { project }),
  gitSetIdentity: (project, name, email) =>
    invoke("git.set_identity", { project, name, email }),
  gitBranches: (project) => invoke("git.branches", { project }),
  gitCreateBranch: (project, name, checkout = true) =>
    invoke("git.create_branch", { project, name, checkout }),
  gitCheckout: (project, name) => invoke("git.checkout", { project, name }),
  gitLog: (project, limit = 50) => invoke("git.log", { project, limit }),
  gitFileHistory: (project, path, limit = 50) =>
    invoke("git.file_history", { project, path, limit }),
  gitAcceptCurrent: (project, path) => invoke("git.accept_current", { project, path }),
  gitAcceptIncoming: (project, path) => invoke("git.accept_incoming", { project, path }),
  gitGenerateCommitMessage: (project) =>
    invoke("git.generate_commit_message", { project }),
  proposalList: (project, includeInactive = false) =>
    invoke("proposal.list", { project, include_inactive: includeInactive }),
  proposalDiff: (project, proposalId, path) =>
    invoke("proposal.diff", { project, proposal_id: proposalId, path }),
  proposalPreview: (project, proposalId, path) =>
    invoke("proposal.preview", { project, proposal_id: proposalId, path }),
  proposalApply: (project, proposalId, path) =>
    invoke("proposal.apply", { project, proposal_id: proposalId, path }),
  proposalOverrideApply: (project, proposalId, path) =>
    invoke("proposal.override_apply", { project, proposal_id: proposalId, path }),
  proposalApplyAll: (project, onlyPassing = true) =>
    invoke("proposal.apply_all", { project, only_passing: onlyPassing }),
  proposalDiscard: (project, proposalId, path) =>
    invoke("proposal.discard", { project, proposal_id: proposalId, path }),
  proposalDiscardAll: (project) => invoke("proposal.discard_all", { project }),
  modelGetConfig: () => invoke("model.get_config"),
  modelSetConfig: (config) => invoke("model.set_config", config),
  modelHealth: () => invoke("model.health"),
  modelCapabilities: () => invoke("model.capabilities"),
  modelPlan: (project, prompt, activePath, forcedPaths = [], openPaths = [], maxBytes = null, forcedFiles = {}) =>
    invoke("model.plan", { project, prompt, active_path: activePath, forced_paths: forcedPaths, open_paths: openPaths, max_bytes: maxBytes, forced_files: forcedFiles }),
  modelReplan: (project, prompt, previousPlanId, activePath, forcedPaths = [], openPaths = [], maxBytes = null, forcedFiles = {}) =>
    invoke("model.replan", { project, prompt, previous_plan_id: previousPlanId, active_path: activePath, forced_paths: forcedPaths, open_paths: openPaths, max_bytes: maxBytes, forced_files: forcedFiles }),
  modelCode: (project, planId, activePath, forcedPaths = [], openPaths = [], maxBytes = null, forcedFiles = {}) =>
    invoke("model.code", { project, plan_id: planId, active_path: activePath, forced_paths: forcedPaths, open_paths: openPaths, max_bytes: maxBytes, forced_files: forcedFiles }),
  modelReview: (project, planId, code, files) =>
    invoke("model.review", { project, plan_id: planId, code, files }),
  modelRunAgent: (project, prompt, activePath) =>
    invoke("model.run_agent", { project, prompt, active_path: activePath }),
  modelRunStatus: (project, runId) =>
    invoke("model.run_status", { project, run_id: runId }),
};
