import fs from "node:fs/promises";
import path from "node:path";
import chokidar from "chokidar";

const IGNORED_DIRS = new Set([".git", "node_modules", "__pycache__", ".venv", "venv", ".pytest_cache", "dist", "build"]);
const BOB_STATE_FILES = new Set(["changes.json", "index.json", "runs.json", "model_runs.json", "snapshots.json", "staged.json"]);

function shouldIgnore(filePath, workspaceRoot) {
  const relative = path.relative(workspaceRoot, filePath);
  const parts = relative.split(path.sep);
  if (parts.some((part) => IGNORED_DIRS.has(part))) return true;
  const bobIndex = parts.indexOf(".bob");
  return bobIndex >= 0 && !BOB_STATE_FILES.has(parts.at(-1));
}

export class WorkspaceWatcher {
  constructor({ workspaceRoot, io, debounceMs = 80 }) {
    this.workspaceRoot = path.resolve(workspaceRoot);
    this.io = io;
    this.debounceMs = debounceMs;
    this.pending = new Map();
    this.runStates = new Map();
    this.watcher = null;
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
    const [project, ...rest] = relative.split(path.sep);
    if (!project || rest.length === 0) return;
    const relPath = rest.join("/");
    const current = this.pending.get(project) || { paths: new Set(), bob: false, runs: false, timer: null };
    if (relPath.startsWith(".bob/")) {
      current.bob = true;
      if (relPath === ".bob/runs.json") current.runs = true;
    } else {
      current.paths.add(relPath);
    }
    clearTimeout(current.timer);
    current.timer = setTimeout(() => this.flush(project), this.debounceMs);
    this.pending.set(project, current);
  }

  async flush(project) {
    const state = this.pending.get(project);
    if (!state) return;
    this.pending.delete(project);
    const room = `workspace:${project}`;
    const paths = [...state.paths].sort();
    if (paths.length) this.io.to(room).emit("workspace:changed", { project, paths });
    if (state.bob || paths.length) this.io.to(room).emit("worktree:changed", { project });
    if (state.runs) await this.emitRunUpdates(project, room);
  }

  async emitRunUpdates(project, room) {
    try {
      const filePath = path.join(this.workspaceRoot, project, ".bob", "runs.json");
      const parsed = JSON.parse(await fs.readFile(filePath, "utf8"));
      const runs = parsed.runs || [];
      for (const run of runs) {
        const key = `${project}:${run.run_id || run.id}`;
        const signature = JSON.stringify(run);
        if (this.runStates.get(key) !== signature) {
          this.runStates.set(key, signature);
          this.io.to(room).emit("model:run", { project, ...run });
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
