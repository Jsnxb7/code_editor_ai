import path from "node:path";
import { spawn } from "node:child_process";
import { fileURLToPath } from "node:url";
import { safeWorkspacePath } from "./workspace-path.js";

const here = path.dirname(fileURLToPath(import.meta.url));

class PyrightProcess {
  constructor({ project, room, root, namespace }) {
    this.project = project;
    this.room = room;
    this.root = root;
    this.namespace = namespace;
    this.buffer = Buffer.alloc(0);
    this.process = null;
  }

  start() {
    const script = path.resolve(here, "..", "node_modules", "pyright", "langserver.index.js");
    this.process = spawn(process.execPath, [script, "--stdio"], {
      cwd: this.root,
      stdio: ["pipe", "pipe", "pipe"],
      windowsHide: true,
    });
    this.process.stdout.on("data", (chunk) => this.read(chunk));
    this.process.stderr.on("data", (chunk) => console.warn(`[pyright:${this.project}] ${String(chunk).trim()}`));
    this.process.on("error", (error) => console.warn(`[pyright:${this.project}] ${error.message}`));
    this.process.on("exit", () => {
      this.process = null;
    });
  }

  send(message) {
    if (!this.process) this.start();
    const body = Buffer.from(JSON.stringify(message), "utf8");
    this.process?.stdin.write(`Content-Length: ${body.length}\r\n\r\n`);
    this.process?.stdin.write(body);
  }

  read(chunk) {
    this.buffer = Buffer.concat([this.buffer, chunk]);
    while (true) {
      const headerEnd = this.buffer.indexOf("\r\n\r\n");
      if (headerEnd < 0) return;
      const header = this.buffer.subarray(0, headerEnd).toString("utf8");
      const match = /content-length:\s*(\d+)/i.exec(header);
      if (!match) {
        this.buffer = this.buffer.subarray(headerEnd + 4);
        continue;
      }
      const length = Number(match[1]);
      const bodyStart = headerEnd + 4;
      if (this.buffer.length < bodyStart + length) return;
      const body = this.buffer.subarray(bodyStart, bodyStart + length);
      this.buffer = this.buffer.subarray(bodyStart + length);
      try {
        this.namespace.to(this.room).emit("lsp:message", JSON.parse(body.toString("utf8")));
      } catch (error) {
        console.warn(`[pyright:${this.project}] Invalid JSON: ${error.message}`);
      }
    }
  }

  stop() {
    this.process?.kill();
    this.process = null;
  }
}

export class LspManager {
  constructor({ io, workspaceRoot, authenticate = () => null, resolveWorkspace = () => { throw new Error("Workspace access denied"); } }) {
    this.namespace = io.of("/lsp");
    this.workspaceRoot = workspaceRoot;
    this.authenticate = authenticate;
    this.resolveWorkspace = resolveWorkspace;
    this.processes = new Map();
    this.clients = new Map();
  }

  register() {
    this.namespace.use((socket, next) => {
      const context = this.authenticate(socket.request);
      if (!context) return next(new Error("Authentication required"));
      socket.data.auth = context;
      next();
    });
    this.namespace.on("connection", (socket) => {
      socket.on("lsp:join", (data = {}) => {
        try {
          const project = String(data.project || "");
          const projectRef = this.resolveWorkspace(socket.data.auth.user, project);
          const root = safeWorkspacePath(this.workspaceRoot, projectRef);
          const processKey = projectRef;
          socket.join(processKey);
          socket.data.project = project;
          socket.data.projectRef = projectRef;
          socket.data.processKey = processKey;
          const clients = this.clients.get(processKey) || new Set();
          clients.add(socket.id);
          this.clients.set(processKey, clients);
          if (!this.processes.has(processKey)) {
            this.processes.set(processKey, new PyrightProcess({ project, room: processKey, root, namespace: this.namespace }));
          }
          socket.emit("lsp:ready", { project });
        } catch (error) {
          socket.emit("lsp:error", { message: error.message });
        }
      });
      socket.on("lsp:message", (data = {}) => {
        const project = socket.data.project;
        const processKey = socket.data.processKey;
        try {
          if (project && processKey && this.resolveWorkspace(socket.data.auth.user, project) === socket.data.projectRef && data.message) this.processes.get(processKey)?.send(data.message);
        } catch (error) {
          socket.emit("lsp:error", { message: error.message });
        }
      });
      socket.on("disconnect", () => this.release(socket));
    });
    return this;
  }

  release(socket) {
    const processKey = socket.data.processKey;
    if (!processKey) return;
    const clients = this.clients.get(processKey);
    clients?.delete(socket.id);
    if (!clients?.size) {
      this.clients.delete(processKey);
      this.processes.get(processKey)?.stop();
      this.processes.delete(processKey);
    }
  }

  close() {
    for (const process of this.processes.values()) process.stop();
    this.processes.clear();
    this.clients.clear();
  }
}
