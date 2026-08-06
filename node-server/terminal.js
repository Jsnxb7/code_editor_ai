import os from "node:os";
import pty from "node-pty";
import { safeWorkspacePath } from "./workspace-path.js";

function sessionKey(socketId, terminalId) {
  return `${socketId}:${terminalId}`;
}

export class TerminalManager {
  constructor({ workspaceRoot, shell = "", ptyModule = pty, authorize = () => true }) {
    this.workspaceRoot = workspaceRoot;
    this.shell = shell;
    this.pty = ptyModule;
    this.authorize = authorize;
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
      const cwd = safeWorkspacePath(this.workspaceRoot, String(data.project || "sample_project"));
      if (!this.authorize(socket, String(data.project || "sample_project"))) throw new Error("Workspace access denied");
      this.dispose(socket.id, terminalId);
      const shell = this.shell || (os.platform() === "win32" ? process.env.COMSPEC || "powershell.exe" : process.env.SHELL || "/bin/bash");
      const args = os.platform() === "win32" ? [] : ["-i"];
      const session = this.pty.spawn(shell, args, {
        name: "xterm-256color",
        cols: 80,
        rows: 24,
        cwd,
        env: { ...process.env, TERM: "xterm-256color", BOB_IDE: "1" },
        useConptyDll: os.platform() === "win32",
      });
      const key = sessionKey(socket.id, terminalId);
      this.sessions.set(key, session);
      session.onData((text) => socket.emit("terminal:data", { terminalId, data: text }));
      session.onExit(() => {
        if (this.sessions.get(key) !== session) return;
        this.sessions.delete(key);
        socket.emit("terminal:exit", { terminalId });
      });
      socket.emit("terminal:ready", { terminalId, cwd });
    } catch (error) {
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
