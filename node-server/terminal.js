import os from "node:os";
import pty from "node-pty";
import { safeWorkspacePath } from "./workspace-path.js";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const terminalModuleRoot = path.dirname(fileURLToPath(import.meta.url));
const terminalInitPath = path.join(terminalModuleRoot, "terminal-init.sh");

function sessionKey(socketId, terminalId) {
  return `${socketId}:${terminalId}`;
}

export class TerminalManager {
  constructor({ workspaceRoot, shell = "", ptyModule = pty, resolveWorkspace = () => { throw new Error("Workspace access denied"); }, sandboxImage = "", audit = null, maxTerminalsPerUser = 4 }) {
    this.workspaceRoot = workspaceRoot;
    this.shell = shell;
    this.pty = ptyModule;
    this.resolveWorkspace = resolveWorkspace;
    this.sandboxImage = sandboxImage;
    this.audit = audit;
    this.maxTerminalsPerUser = maxTerminalsPerUser;
    this.sessions = new Map();
  }

  register(socket) {
    socket.on("terminal:create", (data = {}) => this.create(socket, data));
    socket.on("terminal:input", (data = {}) => {
      this.sessions.get(sessionKey(socket.id, String(data.terminalId || "default")))?.write(String(data.data || ""));
    });
    socket.on("terminal:resize", (data = {}) => {
      const session = this.sessions.get(sessionKey(socket.id, String(data.terminalId || "default")));
      if (session) session.resize(Math.max(2, Number(data.cols) || 80), Math.max(1, Number(data.rows) || 24));
    });
    socket.on("terminal:dispose", (data = {}) => this.dispose(socket.id, String(data.terminalId || "default")));
    socket.on("disconnect", () => this.disposeSocket(socket.id));
  }

  create(socket, data) {
    const terminalId = String(data.terminalId || "default");
    try {
      const project = String(data.project || "sample_project");
      const resolved = this.resolveWorkspace(socket, project);
      const cwd = safeWorkspacePath(this.workspaceRoot, resolved.projectRef);
      const workspaceRoot = path.resolve(this.workspaceRoot);
      const userRoot = path.resolve(resolved.userRoot);
      if (userRoot === workspaceRoot || !userRoot.startsWith(`${workspaceRoot}${path.sep}`)) throw new Error("Invalid user workspace root");
      const realWorkspaceRoot = fs.realpathSync(workspaceRoot);
      const realUserRoot = fs.realpathSync(userRoot);
      const realProjectRoot = fs.realpathSync(cwd);
      if (realUserRoot === realWorkspaceRoot || !realUserRoot.startsWith(`${realWorkspaceRoot}${path.sep}`)) throw new Error("User workspace escapes storage root");
      if (realProjectRoot === realUserRoot || !realProjectRoot.startsWith(`${realUserRoot}${path.sep}`)) throw new Error("Project escapes user workspace root");
      const projectRelative = path.relative(userRoot, cwd);
      if (!projectRelative || path.isAbsolute(projectRelative) || projectRelative === ".." || projectRelative.startsWith(`..${path.sep}`)) throw new Error("Invalid active project path");
      const containerProject = `/workspace/${projectRelative.split(path.sep).join("/")}`;
      this.dispose(socket.id, terminalId);
      const userId = String(socket.data?.auth?.user?.id || "anonymous");
      const activeForUser = [...this.sessions.values()].filter((item) => item.__bobUserId === userId).length;
      if (activeForUser >= this.maxTerminalsPerUser) throw new Error(`Terminal limit reached (${this.maxTerminalsPerUser} per user)`);
      if (!this.sandboxImage) throw new Error("A container terminal is required for every user. Configure BOB_TERMINAL_SANDBOX_IMAGE.");
      const shell = "docker";
      const args = [
        "run", "--rm", "-it", "--network", "none", "--cpus", "1", "--memory", "1g", "--pids-limit", "256",
        "--read-only", "--cap-drop", "ALL", "--security-opt", "no-new-privileges", "--tmpfs", "/tmp:rw,nosuid,size=256m",
        "--mount", `type=bind,source=${userRoot},target=/workspace`,
        "--mount", `type=bind,source=${terminalInitPath},target=/etc/bob-terminal-init.sh,readonly`, "-w", containerProject,
        "--env", `HOME=/workspace/.bob/runtime/${userId}`, "--env", `BOB_USER_ID=${userId}`, "--env", "BOB_USER_ROOT=/workspace",
        "--env", `BOB_WORKSPACE=${containerProject}`, "--env", `BOB_ACTIVE_PROJECT=${project}`, "--env", "BOB_TERMINAL_ROOT=/workspace", "--env", `BOB_TERMINAL_START=${containerProject}`,
        this.sandboxImage, "/bin/bash", "--noprofile", "--rcfile", "/etc/bob-terminal-init.sh", "-i",
      ];
      const runtimeRoot = path.join(userRoot, ".bob", "runtime", userId);
      fs.mkdirSync(runtimeRoot, { recursive: true });
      const inherited = Object.fromEntries(["PATH", "PATHEXT", "SystemRoot", "COMSPEC", "WINDIR", "LANG", "LC_ALL", "SHELL"].map((name) => [name, process.env[name]]).filter(([, value]) => value));
      const session = this.pty.spawn(shell, args, {
        name: "xterm-256color",
        cols: 80,
        rows: 24,
        cwd,
        env: { ...inherited, TERM: "xterm-256color", BOB_IDE: "1", BOB_USER_ID: userId, BOB_WORKSPACE: cwd, HOME: runtimeRoot, USERPROFILE: runtimeRoot, TEMP: runtimeRoot, TMP: runtimeRoot },
        useConptyDll: os.platform() === "win32",
      });
      const key = sessionKey(socket.id, terminalId);
      session.__bobUserId = userId;
      this.sessions.set(key, session);
      session.onData((text) => socket.emit("terminal:data", { terminalId, data: text }));
      session.onExit(() => {
        if (this.sessions.get(key) !== session) return;
        this.sessions.delete(key);
        this.audit?.("terminal.exited", { actor_user_id: socket.data?.auth?.user?.id, request_id: socket.data?.requestId, socket_id: socket.id, terminal_id: terminalId, project: String(data.project || "sample_project") });
        socket.emit("terminal:exit", { terminalId });
      });
      this.audit?.("terminal.created", { actor_user_id: socket.data?.auth?.user?.id, request_id: socket.data?.requestId, socket_id: socket.id, terminal_id: terminalId, project, shell: "container-bash", sandboxed: true });
      socket.emit("terminal:ready", { terminalId, cwd: `/${projectRelative.split(path.sep).join("/")}`, project, sandboxed: true });
    } catch (error) {
      this.audit?.("terminal.error", { actor_user_id: socket.data?.auth?.user?.id, request_id: socket.data?.requestId, socket_id: socket.id, terminal_id: terminalId, project: String(data.project || "sample_project"), error: { type: error.name, message: error.message } });
      socket.emit("terminal:error", { terminalId, message: error.message });
    }
  }

  dispose(socketId, terminalId) {
    const key = sessionKey(socketId, terminalId);
    const session = this.sessions.get(key);
    this.sessions.delete(key);
    if (session) {
      try {
        session.kill();
      } catch {
        // Process already exited.
      }
    }
  }

  disposeSocket(socketId) {
    for (const key of [...this.sessions.keys()]) {
      if (key.startsWith(`${socketId}:`)) this.dispose(socketId, key.slice(socketId.length + 1));
    }
  }

  close() {
    for (const key of [...this.sessions.keys()]) {
      const separator = key.indexOf(":");
      this.dispose(key.slice(0, separator), key.slice(separator + 1));
    }
  }
}
