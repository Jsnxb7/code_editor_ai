import fs from "node:fs/promises";
import path from "node:path";
import chokidar from "chokidar";

const IGNORED_DIRS = new Set(["node_modules", "__pycache__", ".venv", "venv", ".pytest_cache", "dist", "build"]);
const BOB_STATE_FILES = new Set(["plans.json", "proposals.json", "runs.json", "model_runs.json"]);
const GIT_STATE_FILES = new Set(["HEAD", "index", "MERGE_HEAD", "CHERRY_PICK_HEAD", "REVERT_HEAD", "rebase-merge", "rebase-apply"]);

function shouldIgnore(filePath, workspaceRoot) {
  const relative = path.relative(workspaceRoot, filePath);
  const parts = relative.split(path.sep);
  if (parts.some((part) => IGNORED_DIRS.has(part))) return true;
  const gitIndex = parts.indexOf(".git");
  if (gitIndex >= 0) {
    const gitParts = parts.slice(gitIndex + 1);
    return !(
      GIT_STATE_FILES.has(gitParts[0])
      || gitParts[0] === "refs"
      || gitParts[0] === "packed-refs"
    );
  }
  const bobIndex = parts.indexOf(".bob");
  return bobIndex >= 0 && !BOB_STATE_FILES.has(parts.at(-1));
}

export class WorkspaceWatcher {
  constructor({ workspaceRoot, io, debounceMs = 80, onRunUpdate = null }) {
    this.workspaceRoot = path.resolve(workspaceRoot);
    this.io = io;
    this.debounceMs = debounceMs;
    this.pending = new Map();
    this.runStates = new Map();
    this.watcher = null;
    this.onRunUpdate = onRunUpdate;
  }

  start() {
    this.watcher = chokidar.watch(this.workspaceRoot, {
      ignoreInitial: true,
      awaitWriteFinish: { stabilityThreshold: 60, pollInterval: 20 },
      ignored: (filePath) => shouldIgnore(filePath, this.workspaceRoot),
    });
    for (const event of ["add", "change", "unlink", "addDir", "unlinkDir"]) {
      this.watcher.on(event, (filePath) => this.queue(filePath));
    }
    return this;
  }

  queue(filePath) {
    const relative = path.relative(this.workspaceRoot, filePath);
    if (!relative || relative.startsWith("..")) return;
    const [scope, project, ...rest] = relative.split(path.sep);
    if (!scope || !project || rest.length === 0 || !scope.includes("--")) return;
    const projectRef = `${scope}/${project}`;
    const relPath = rest.join("/");
    const current = this.pending.get(projectRef) || {
      paths: new Set(), bob: false, git: false, proposal: false, plans: false, runs: false, timer: null,
    };
    if (relPath.startsWith(".git/")) {
      current.git = true;
    } else if (relPath.startsWith(".bob/")) {
      current.bob = true;
      if (relPath === ".bob/runs.json") current.runs = true;
      if (relPath === ".bob/plans.json") current.plans = true;
      if (relPath === ".bob/proposals.json") current.proposal = true;
    } else {
      current.paths.add(relPath);
    }
    clearTimeout(current.timer);
    current.timer = setTimeout(() => this.flush(projectRef), this.debounceMs);
    this.pending.set(projectRef, current);
  }

  async flush(projectRef) {
    const state = this.pending.get(projectRef);
    if (!state) return;
    this.pending.delete(projectRef);
    const project = projectRef.split("/").at(-1);
    const room = `workspace:${projectRef}`;
    const paths = [...state.paths].sort();
    if (paths.length) this.io.to(room).emit("workspace:changed", { project, paths });
    if (state.git || paths.length) this.io.to(room).emit("git:changed", { project });
    if (state.plans) this.io.to(room).emit("plans:changed", { project });
    if (state.proposal) this.io.to(room).emit("proposal:changed", { project });
    if (state.git || state.bob || paths.length) {
      this.io.to(room).emit("source-control:changed", { project });
      this.io.to(room).emit("worktree:changed", { project });
    }
    if (state.runs) await this.emitRunUpdates(project, projectRef, room);
  }

  async emitRunUpdates(project, projectRef, room) {
    try {
      const filePath = path.join(this.workspaceRoot, ...projectRef.split("/"), ".bob", "runs.json");
      const parsed = JSON.parse(await fs.readFile(filePath, "utf8"));
      const runs = parsed.runs || [];
      for (const run of runs) {
        const key = `${projectRef}:${run.run_id || run.id}`;
        const signature = JSON.stringify(run);
        if (this.runStates.get(key) !== signature) {
          this.runStates.set(key, signature);
          this.io.to(room).emit("model:run", { project, ...run });
          await this.onRunUpdate?.(project, projectRef, run);
        }
      }
    } catch {
      // The atomic writer may be between rename operations; the next event retries.
    }
  }

  async close() {
    for (const item of this.pending.values()) clearTimeout(item.timer);
    this.pending.clear();
    await this.watcher?.close();
  }
}
