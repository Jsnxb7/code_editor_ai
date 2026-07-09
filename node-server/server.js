import fs from "node:fs";
import http from "node:http";
import path from "node:path";
import express from "express";
import { Server as SocketServer } from "socket.io";
import { BobMcpClient } from "./mcp-client.js";
import { publicConfig, readConfig, writeConfig } from "./config.js";
import { safeWorkspacePath } from "./workspace-path.js";
import { WorkspaceWatcher } from "./watcher.js";
import { TerminalManager } from "./terminal.js";
import { LspManager } from "./lsp.js";

const MUTATING_TOOLS = new Set([
  "file.write", "file.create", "file.delete", "file.rename",
  "folder.create", "folder.delete", "folder.rename",
  "worktree.stage_change", "worktree.unstage_change", "worktree.stage_all",
  "worktree.unstage_all", "worktree.stage_many", "worktree.unstage_many",
  "worktree.apply_change", "worktree.apply_many", "worktree.apply_all",
  "worktree.apply_passing", "worktree.override_and_apply",
  "worktree.discard_change", "worktree.discard_many", "worktree.discard_all",
  "worktree.stage_hunk", "worktree.discard_hunk", "worktree.apply_hunk",
  "worktree.apply_all_hunks", "worktree.restore_file", "worktree.restore_snapshot",
  "worktree.ignore_path", "worktree.create_snapshot",
  "model.run_agent", "model.plan", "model.set_config",
  "workspace.create", "workspace.import",
]);

export function createServer() {
  let config = readConfig();
  const app = express();
  const server = http.createServer(app);
  const io = new SocketServer(server, { cors: { origin: true, credentials: true } });
  const mcp = new BobMcpClient(() => config);
  const terminal = new TerminalManager({ workspaceRoot: config.workspaceRoot, shell: config.terminalShell });
  const lsp = new LspManager({ io, workspaceRoot: config.workspaceRoot }).register();
  const watcher = new WorkspaceWatcher({ workspaceRoot: config.workspaceRoot, io }).start();

  app.disable("x-powered-by");
  app.use(express.json({ limit: "50mb" }));

  app.get("/api/health", async (_request, response) => {
    const python = await mcp.health();
    response.status(python.ok ? 200 : 503).json({
      ok: python.ok,
      data: {
        service: "Bob Node Gateway",
        node: true,
        python,
        realtime: { socketio: true, watcher: true, terminal: true, lsp: true },
        frontendBuilt: fs.existsSync(path.join(config.frontendDist, "index.html")),
      },
    });
  });

  app.get("/api/config", (_request, response) => {
    response.json({ ok: true, data: publicConfig(config) });
  });

  app.put("/api/config", async (request, response) => {
    try {
      config = writeConfig(request.body || {});
      await mcp.close();
      response.json({ ok: true, data: publicConfig(config) });
    } catch (error) {
      response.status(400).json({ ok: false, error: error.message });
    }
  });

  app.get("/api/mcp/tools", async (_request, response) => {
    try {
      const tools = await mcp.listTools();
      response.json({ ok: true, data: { tools: tools.map((tool) => tool.name).sort() } });
    } catch (error) {
      response.status(503).json({ ok: false, error: error.message });
    }
  });

  app.post("/api/mcp/call", async (request, response) => {
    const name = String(request.body?.name || "");
    const arguments_ = request.body?.arguments || {};
    if (!name) return response.status(400).json({ ok: false, error: "MCP tool name is required" });
    try {
      const data = await mcp.callTool(name, arguments_);
      response.json({ ok: true, data });
      const project = arguments_.project;
      if (project && MUTATING_TOOLS.has(name)) {
        const room = `workspace:${project}`;
        io.to(room).emit("worktree:changed", { project });
        io.to(room).emit("workspace:changed", { project, paths: [] });
      }
      if (name === "model.set_config") io.emit("model:config", data);
    } catch (error) {
      const status = /Unknown|not found/i.test(error.message) ? 400 : 503;
      response.status(status).json({ ok: false, error: error.message });
    }
  });

  io.on("connection", (socket) => {
    socket.emit("connection:ready", {});
    terminal.register(socket);
    socket.on("workspace:join", (data = {}) => {
      try {
        const project = String(data.project || "");
        safeWorkspacePath(config.workspaceRoot, project);
        socket.join(`workspace:${project}`);
        socket.emit("workspace:ready", { project });
      } catch (error) {
        socket.emit("workspace:error", { message: error.message });
      }
    });
    socket.on("workspace:leave", (data = {}) => {
      const project = String(data.project || "");
      if (project) socket.leave(`workspace:${project}`);
    });
    socket.on("editor:change", (data = {}) => {
      try {
        const project = String(data.project || "");
        const filePath = String(data.path || "");
        safeWorkspacePath(config.workspaceRoot, project, filePath);
        socket.to(`workspace:${project}`).emit("editor:change", {
          project,
          path: filePath,
          content: String(data.content || ""),
          clientId: String(data.clientId || ""),
          version: Number(data.version || 0),
        });
      } catch (error) {
        socket.emit("workspace:error", { message: error.message });
      }
    });
  });

  if (fs.existsSync(config.frontendDist)) {
    app.use(express.static(config.frontendDist, { index: false }));
  }
  app.use((request, response) => {
    if (request.path.startsWith("/api/")) {
      return response.status(404).json({ ok: false, error: "API route not found" });
    }
    if (path.extname(request.path)) return response.status(404).send("Asset not found");
    const indexPath = path.join(config.frontendDist, "index.html");
    if (!fs.existsSync(indexPath)) {
      return response.status(503).type("text").send("Frontend build not found. Run: npm run build");
    }
    return response.sendFile(indexPath);
  });

  async function close() {
    terminal.close();
    lsp.close();
    await watcher.close();
    await mcp.close();
    io.close();
  }

  return { app, server, io, mcp, close, getConfig: () => config };
}
