import path from "node:path";
import { spawn } from "node:child_process";
import { fileURLToPath } from "node:url";
import { safeWorkspacePath } from "./workspace-path.js";

const here = path.dirname(fileURLToPath(import.meta.url));

class PyrightProcess {
  constructor({ project, root, namespace }) {
    this.project = project;
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
        this.namespace.to(this.project).emit("lsp:message", JSON.parse(body.toString("utf8")));
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
  constructor({ io, workspaceRoot, authenticate = () => null, authorize = () => true }) {
    this.namespace = io.of("/lsp");
    this.workspaceRoot = workspaceRoot;
    this.authenticate = authenticate;
    this.authorize = authorize;
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
          if (!this.authorize(socket.data.auth.user, project)) throw new Error("Workspace access denied");
          const root = safeWorkspacePath(this.workspaceRoot, project);
          socket.join(project);
          socket.data.project = project;
          const clients = this.clients.get(project) || new Set();
          clients.add(socket.id);
          this.clients.set(project, clients);
          if (!this.processes.has(project)) {
            this.processes.set(project, new PyrightProcess({ project, root, namespace: this.namespace }));
          }
          socket.emit("lsp:ready", { project });
        } catch (error) {
          socket.emit("lsp:error", { message: error.message });
        }
      });
      socket.on("lsp:message", (data = {}) => {
        const project = String(data.project || socket.data.project || "");
        if (project && data.message) this.processes.get(project)?.send(data.message);
      });
      socket.on("disconnect", () => this.release(socket));
    });
    return this;
  }

  release(socket) {
    const project = socket.data.project;
    if (!project) return;
    const clients = this.clients.get(project);
    clients?.delete(socket.id);
    if (!clients?.size) {
      this.clients.delete(project);
      this.processes.get(project)?.stop();
      this.processes.delete(project);
    }
  }

  close() {
    for (const process of this.processes.values()) process.stop();
    this.processes.clear();
    this.clients.clear();
  }
}
