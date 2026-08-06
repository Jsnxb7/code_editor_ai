import fs from "node:fs";
import http from "node:http";
import path from "node:path";
import crypto from "node:crypto";
import express from "express";
import { Server as SocketServer } from "socket.io";
import { BobMcpClient } from "./mcp-client.js";
import { projectRoot, publicConfig, readConfig, writeConfig } from "./config.js";
import { safeWorkspacePath } from "./workspace-path.js";
import { WorkspaceWatcher } from "./watcher.js";
import { TerminalManager } from "./terminal.js";
import { LspManager } from "./lsp.js";
import { AuthStore } from "./auth-store.js";
import { DevStore } from "./dev-store.js";

const MUTATING_TOOLS = new Set([
  "file.write", "file.create", "file.delete", "file.rename", "folder.create", "folder.delete", "folder.rename",
  "worktree.stage_change", "worktree.unstage_change", "worktree.stage_all", "worktree.unstage_all", "worktree.stage_many", "worktree.unstage_many",
  "worktree.apply_change", "worktree.apply_many", "worktree.apply_all", "worktree.apply_passing", "worktree.override_and_apply",
  "worktree.discard_change", "worktree.discard_many", "worktree.discard_all", "worktree.stage_hunk", "worktree.discard_hunk", "worktree.apply_hunk", "worktree.apply_all_hunks",
  "worktree.restore_file", "worktree.restore_snapshot", "worktree.ignore_path", "worktree.create_snapshot",
  "model.run_agent", "model.plan", "model.replan", "model.code", "model.review", "model.set_config", "plans.select", "plans.discard",
  "workspace.create", "workspace.import", "git.init", "git.stage", "git.unstage", "git.stage_all", "git.unstage_all", "git.stage_hunk",
  "git.discard_hunk", "git.discard", "git.discard_all", "git.commit", "git.set_identity", "git.create_branch", "git.checkout", "git.restore_file",
  "git.accept_current", "git.accept_incoming", "proposal.apply", "proposal.override_apply", "proposal.apply_all", "proposal.discard", "proposal.discard_all",
]);

const HIGH_RISK_TOOLS = new Set(["proposal.override_apply", "worktree.override_and_apply", "git.discard", "git.discard_all", "git.discard_hunk", "worktree.discard_all"]);
const ADMIN_ONLY_TOOLS = new Set(["model.set_config"]);
const TRACED_MODEL_TOOLS = new Set(["model.chat", "model.plan", "model.replan", "model.code", "model.review", "model.run_agent"]);
const PUBLIC_PATHS = new Set(["/api/health", "/api/auth/status", "/api/auth/setup", "/api/auth/login"]);
const requestMeta = (request) => ({ ip: request.ip, user_agent: request.headers["user-agent"] || "", request_id: request.requestId });
const errorStatus = (error) => Number(error.status) || (/not found/i.test(error.message) ? 404 : 400);
const targetFor = (name, args) => name.includes("proposal") ? args.proposal_id || args.change_id : args.path || args.change_id || "all";
const argumentSizes = (args) => Object.fromEntries(Object.entries(args).filter(([key]) => !["approval_token", "reason"].includes(key)).map(([key, value]) => [key, typeof value === "string" ? value.length : Buffer.byteLength(JSON.stringify(value ?? null))]));

export function createServer(options = {}) {
  let config = { ...readConfig(), ...(options.workspaceRoot ? { workspaceRoot: options.workspaceRoot } : {}) };
  const app = express(); const server = http.createServer(app);
  const applyServerTimeouts = () => { server.requestTimeout = 0; server.timeout = 0; }; applyServerTimeouts();
  const io = new SocketServer(server, { cors: { origin: true, credentials: true } });
  const dataRoot = options.dataRoot || path.join(projectRoot, "data");
  const dev = new DevStore({ dataRoot, emit: (event, payload) => io.to("role:admin").emit(event, payload) });
  const auth = new AuthStore({ dataRoot, workspaceRoot: config.workspaceRoot, audit: (type, payload) => dev.appendLog(type, payload) });
  const mcp = new BobMcpClient(() => config);
  const terminal = new TerminalManager({ workspaceRoot: config.workspaceRoot, shell: config.terminalShell, authorize: (socket, project) => auth.canAccess(socket.data.auth?.user, project) });
  const lsp = new LspManager({ io, workspaceRoot: config.workspaceRoot, authenticate: (request) => auth.authenticate(request), authorize: (user, project) => auth.canAccess(user, project) }).register();
  const watcher = new WorkspaceWatcher({ workspaceRoot: config.workspaceRoot, io, debounceMs: 40, onRunUpdate: async (project, run) => {
    if (run.status === "dlq_pending") {
      const existing = dev.list("dlq").dlq.some((item) => item.run_id === run.run_id);
      if (!existing) dev.createDlq({ owner_user_id: auth.ownerOf(project), workspace_id: project, run_id: run.run_id, trace_id: run.run_id, request_id: run.request_id || null, component: run.error?.component || "colab", stage: run.error?.stage || run.mode || "agent", prompt: run.user_prompt || "", context_metadata: run.context_metadata || [], attempts: run.error?.attempts || [], prompt_version: run.prompt_version || "unversioned", model_version: run.model_id || "unknown", usage: run.usage || null, error: run.error });
    }
    if (String(run.final_status).toUpperCase() === "FAIL" && run.status === "completed") {
      const existing = dev.list("reviews").reviews.some((item) => item.run_id === run.run_id);
      if (!existing) dev.createFailedReview({ owner_user_id: auth.ownerOf(project), workspace_id: project, run_id: run.run_id, proposal_id: run.linked_proposals?.[0] || null, prompt: run.user_prompt || "", context_metadata: run.context_metadata || [], review: run.review || "Reviewer returned FAIL", model_version: run.model_id || "unknown", prompt_version: run.prompt_version || "unversioned" });
    }
  } }).start();

  app.disable("x-powered-by"); app.use(express.json({ limit: "50mb" }));
  app.use((request, response, next) => { request.requestId = request.headers["x-bob-request-id"] || crypto.randomUUID(); response.setHeader("X-Bob-Request-Id", request.requestId); next(); });

  app.get("/api/health", async (_request, response) => { const python = await mcp.health(); response.status(python.ok ? 200 : 503).json({ ok: python.ok, data: { service: "Bob Node Gateway", node: true, python: python.ok, frontendBuilt: fs.existsSync(path.join(config.frontendDist, "index.html")) } }); });
  app.get("/api/auth/status", (_request, response) => response.json({ ok: true, data: auth.status() }));
  app.post("/api/auth/setup", async (request, response) => {
    try {
      if (!request.ip?.includes("127.0.0.1") && request.ip !== "::1" && request.ip !== "localhost") throw Object.assign(new Error("Initial setup is available only from this computer"), { status: 403 });
      const result = await auth.setup(request.body || {}, requestMeta(request)); response.setHeader("Set-Cookie", auth.cookie(result.session_token)); response.status(201).json({ ok: true, data: { user: result.user, csrf_token: result.csrf_token, expires_at: result.expires_at } });
    } catch (error) { response.status(errorStatus(error)).json({ ok: false, error: error.message, request_id: request.requestId }); }
  });
  app.post("/api/auth/login", async (request, response) => {
    try { const result = await auth.login(request.body?.username, request.body?.password, requestMeta(request)); response.setHeader("Set-Cookie", auth.cookie(result.session_token)); response.json({ ok: true, data: { user: result.user, csrf_token: result.csrf_token, expires_at: result.expires_at } }); }
    catch (error) { response.status(errorStatus(error)).json({ ok: false, error: error.message, request_id: request.requestId }); }
  });

  app.use("/api", (request, response, next) => {
    if (PUBLIC_PATHS.has(request.path)) return next();
    const context = auth.authenticate(request); if (!context) return response.status(401).json({ ok: false, error: "Authentication required", request_id: request.requestId });
    request.auth = context;
    if (!["GET", "HEAD", "OPTIONS"].includes(request.method) && !context.csrf_token_valid(request.headers["x-csrf-token"])) return response.status(403).json({ ok: false, error: "Invalid CSRF token", request_id: request.requestId });
    next();
  });

  const requireAdmin = (request, response, next) => request.auth?.user.role === "admin" ? next() : response.status(403).json({ ok: false, error: "Administrator access required", request_id: request.requestId });
  const requireWorkspace = (request, response, project) => { if (!auth.canAccess(request.auth.user, project)) { response.status(403).json({ ok: false, error: "Workspace access denied", request_id: request.requestId }); return false; } return true; };

  app.get("/api/auth/me", (request, response) => { const csrfToken = auth.rotateCsrf(request.auth.session.id); response.json({ ok: true, data: { user: request.auth.user, csrf_token: csrfToken, expires_at: request.auth.session.absolute_expires_at } }); });
  app.post("/api/auth/logout", (request, response) => { auth.logout(auth.rawCookie(request), request.auth.user); response.setHeader("Set-Cookie", auth.clearCookie()); response.json({ ok: true, data: { logged_out: true } }); });
  app.get("/api/auth/users", requireAdmin, (_request, response) => response.json({ ok: true, data: { users: auth.listUsers() } }));
  app.post("/api/auth/users", requireAdmin, async (request, response) => { try { response.status(201).json({ ok: true, data: { user: await auth.createUser(request.body || {}, request.auth.user) } }); } catch (error) { response.status(errorStatus(error)).json({ ok: false, error: error.message }); } });
  app.patch("/api/auth/users/:id", requireAdmin, async (request, response) => { try { response.json({ ok: true, data: { user: await auth.updateUser(request.params.id, request.body || {}, request.auth.user) } }); } catch (error) { response.status(errorStatus(error)).json({ ok: false, error: error.message }); } });
  app.post("/api/approvals", (request, response) => { try { response.status(201).json({ ok: true, data: auth.issueApproval(request.auth.user, request.body || {}) }); } catch (error) { response.status(errorStatus(error)).json({ ok: false, error: error.message }); } });

  app.get("/api/dev/overview", requireAdmin, (_request, response) => response.json({ ok: true, data: dev.overview() }));
  app.get("/api/dev/dlq", requireAdmin, (_request, response) => response.json({ ok: true, data: dev.list("dlq") }));
  app.get("/api/dev/dlq/:id", requireAdmin, (request, response) => { try { response.json({ ok: true, data: dev.detail("dlq", request.params.id) }); } catch (error) { response.status(errorStatus(error)).json({ ok: false, error: error.message }); } });
  app.post("/api/dev/dlq/:id/claim", requireAdmin, (request, response) => { try { response.json({ ok: true, data: dev.claimDlq(request.params.id, request.auth.user, request.body?.root_cause) }); } catch (error) { response.status(errorStatus(error)).json({ ok: false, error: error.message }); } });
  app.post("/api/dev/dlq/:id/correct", requireAdmin, (request, response) => { try { response.json({ ok: true, data: dev.correctDlq(request.params.id, request.auth.user, request.body || {}) }); } catch (error) { response.status(errorStatus(error)).json({ ok: false, error: error.message }); } });
  app.post("/api/dev/dlq/:id/dismiss", requireAdmin, (request, response) => { try { response.json({ ok: true, data: dev.dismissDlq(request.params.id, request.auth.user, request.body?.reason) }); } catch (error) { response.status(errorStatus(error)).json({ ok: false, error: error.message }); } });
  app.get("/api/dev/reviews", requireAdmin, (_request, response) => response.json({ ok: true, data: dev.list("reviews") }));
  app.get("/api/dev/reviews/:id", requireAdmin, (request, response) => { try { response.json({ ok: true, data: dev.detail("reviews", request.params.id) }); } catch (error) { response.status(errorStatus(error)).json({ ok: false, error: error.message }); } });
  app.post("/api/dev/reviews/:id/correct", requireAdmin, (request, response) => { try { response.json({ ok: true, data: dev.correctReview(request.params.id, request.auth.user, request.body || {}) }); } catch (error) { response.status(errorStatus(error)).json({ ok: false, error: error.message }); } });
  app.get("/api/dev/evaluations", requireAdmin, (_request, response) => response.json({ ok: true, data: dev.list("evaluations") }));
  app.get("/api/dev/evaluations/export", requireAdmin, (_request, response) => response.json({ ok: true, data: dev.exportEvaluations() }));
  app.get("/api/dev/evaluations/:id", requireAdmin, (request, response) => { try { response.json({ ok: true, data: dev.detail("evaluations", request.params.id) }); } catch (error) { response.status(errorStatus(error)).json({ ok: false, error: error.message }); } });
  app.post("/api/dev/evaluations", requireAdmin, (request, response) => { try { response.status(201).json({ ok: true, data: dev.createEvaluation(request.auth.user, request.body || {}) }); } catch (error) { response.status(errorStatus(error)).json({ ok: false, error: error.message }); } });
  app.get("/api/dev/corrections", requireAdmin, (_request, response) => response.json({ ok: true, data: dev.list("corrections") }));
  app.get("/api/dev/corrections/:id", requireAdmin, (request, response) => { try { response.json({ ok: true, data: dev.detail("corrections", request.params.id) }); } catch (error) { response.status(errorStatus(error)).json({ ok: false, error: error.message }); } });
  app.get("/api/dev/logs", requireAdmin, (request, response) => response.json({ ok: true, data: { logs: dev.logs(request.query) } }));

  app.get("/api/config", (_request, response) => response.json({ ok: true, data: publicConfig(config) }));
  app.put("/api/config", requireAdmin, async (request, response) => { try { config = writeConfig(request.body || {}); applyServerTimeouts(); await mcp.close(); response.json({ ok: true, data: publicConfig(config) }); } catch (error) { response.status(400).json({ ok: false, error: error.message }); } });
  app.get("/api/mcp/tools", async (_request, response) => { try { const tools = await mcp.listTools(); response.json({ ok: true, data: { tools: tools.map((tool) => ({ name: tool.name, description: tool.description || "", input_schema: tool.inputSchema || {} })).sort((a, b) => a.name.localeCompare(b.name)), names: tools.map((tool) => tool.name).sort() } }); } catch (error) { response.status(503).json({ ok: false, error: error.message }); } });

  app.post("/api/mcp/call", async (request, response) => {
    const name = String(request.body?.name || ""); const args = { ...(request.body?.arguments || {}) }; const started = performance.now();
    if (!name) return response.status(400).json({ ok: false, error: "MCP tool name is required" });
    try {
      if (ADMIN_ONLY_TOOLS.has(name) && request.auth.user.role !== "admin") throw Object.assign(new Error("Administrator access required"), { status: 403 });
      if (args.project && !requireWorkspace(request, response, String(args.project))) return;
      if (TRACED_MODEL_TOOLS.has(name)) { args.request_id = request.requestId; args.actor_user_id = request.auth.user.id; }
      const highRisk = HIGH_RISK_TOOLS.has(name) || (["worktree.apply_all", "worktree.apply_many"].includes(name) && args.override === true) || (name === "worktree.discard_change" && String(args.change_id || "").startsWith("git:"));
      let approval = null;
      if (highRisk) { approval = auth.consumeApproval(request.auth.user, args.approval_token, { operation: name, project: String(args.project), target: targetFor(name, args) }); delete args.approval_token; }
      const reason = approval?.reason || args.reason; delete args.reason;
      let data = await mcp.callTool(name, args);
      if (name === "workspace.list") data = { ...data, projects: auth.projectsFor(request.auth.user, data.projects || []) };
      if (["workspace.create", "workspace.import"].includes(name) && data.project) auth.assignOwner(data.project, request.auth.user.id, request.auth.user);
      const project = args.project || data?.project;
      if (name === "model.review" && String(data?.final_status || data?.run?.final_status).toUpperCase() === "FAIL") {
        const failed = dev.createFailedReview({ owner_user_id: request.auth.user.id, workspace_id: project, run_id: data?.run?.run_id, proposal_id: data?.proposal?.proposal_id, prompt: data?.run?.user_prompt || "", context_metadata: data?.run?.context_metadata || [], review: data?.review || data?.run?.review || "Reviewer returned FAIL", model_version: data?.run?.model_version || "unknown", prompt_version: data?.run?.prompt_version || "unversioned" });
        data = { ...data, failed_review_id: failed.id };
      }
      if (["proposal.override_apply", "worktree.override_and_apply", "worktree.apply_all", "worktree.apply_many"].includes(name) && (!["worktree.apply_all", "worktree.apply_many"].includes(name) || request.body?.arguments?.override === true)) {
        const paths = [...new Set([...(data?.applied || []), ...(data?.proposal?.files?.filter((item) => item.status === "applied").map((item) => item.path) || []), ...((data?.results || []).flatMap((item) => item?.applied || item?.proposal?.files?.filter((file) => file.status === "applied").map((file) => file.path) || []))])];
        const staged = [], stage_errors = [];
        for (const filePath of paths) { try { await mcp.callTool("git.stage", { project, path: filePath }); staged.push(filePath); } catch (error) { stage_errors.push({ path: filePath, error: error.message }); } }
        const targets = JSON.stringify({ proposal_id: args.proposal_id, change_id: args.change_id, change_ids: args.change_ids });
        const reviews = dev.list("reviews").reviews.filter((item) => item.proposal_id && ((name === "worktree.apply_all" && item.workspace_id === project) || targets.includes(item.proposal_id)));
        for (const review of reviews) dev.recordForce(review.id, { actor_user_id: request.auth.user.id, reason, paths, staged, stage_errors, request_id: request.requestId });
        data = { ...data, force_stage: { staged, errors: stage_errors, reason } };
      }
      const forceApplied = ["proposal.override_apply", "worktree.override_and_apply"].includes(name) || (["worktree.apply_all", "worktree.apply_many"].includes(name) && request.body?.arguments?.override === true);
      const accepted = ["proposal.apply", "proposal.apply_all", "worktree.apply_change", "worktree.apply_many", "worktree.apply_all", "worktree.apply_passing"].includes(name);
      const rejected = ["proposal.discard", "proposal.discard_all"].includes(name) || (["worktree.discard_change", "worktree.discard_many", "worktree.discard_all"].includes(name) && JSON.stringify(request.body?.arguments || {}).includes("proposal:"));
      if (forceApplied || accepted || rejected) {
        const feedback = dev.recordFeedback({ owner_user_id: request.auth.user.id, actor_user_id: request.auth.user.id, workspace_id: project, request_id: request.requestId, trace_id: data?.run?.run_id || null, proposal_id: args.proposal_id || null, target: targetFor(name, args), action: forceApplied ? "force-applied" : rejected ? "rejected" : "accepted", tool: name });
        io.to(`workspace:${project}`).emit("feedback:changed", { project, id: feedback.id, action: feedback.action });
      }
      const usage = data?.run?.usage || data?.usage;
      if (usage) dev.recordUsage({ owner_user_id: request.auth.user.id, workspace_id: project, request_id: request.requestId, trace_id: data?.run?.run_id || args.run_id || null, stage: name, usage, estimated_cost_usd: data?.run?.estimated_cost_usd ?? data?.estimated_cost_usd ?? null, model_id: data?.run?.model_id || data?.model || null, prompt_version: data?.run?.prompt_version || data?.prompt_version || null });
      if (project && MUTATING_TOOLS.has(name)) {
        const room = `workspace:${project}`; if (name.startsWith("git.")) io.to(room).emit("git:changed", { project }); if (name.startsWith("proposal.")) io.to(room).emit("proposal:changed", { project });
        io.to(room).emit("source-control:changed", { project }); io.to(room).emit("worktree:changed", { project }); io.to(room).emit("workspace:changed", { project, paths: [] });
      }
      dev.appendLog("tool.call", { actor_user_id: request.auth.user.id, role: request.auth.user.role, request_id: request.requestId, trace_id: data?.run?.run_id || args.run_id || null, tool: name, project: args.project || null, argument_fields: Object.keys(args), argument_sizes: argumentSizes(args), duration_ms: Math.round(performance.now() - started), retry_count: Number(data?.run?.attempt_count || data?.attempt_count || 1) - 1, status: "success" });
      response.json({ ok: true, data }); if (name === "model.set_config") io.emit("model:config", data);
    } catch (error) {
      const status = Number(error.status) || (/Unknown|not found/i.test(error.message) ? 400 : 503);
      dev.appendLog("tool.error", { actor_user_id: request.auth.user.id, request_id: request.requestId, tool: name, project: args.project || null, duration_ms: Math.round(performance.now() - started), status: "failed", error: { type: error.name, message: error.message } });
      // Staged model runs are persisted as dlq_pending by Python and converted by
      // the watcher. Only stateless chat failures need a gateway-created record.
      if (name === "model.chat" && (error.dlq || /after 3 attempts/i.test(error.message))) dev.createDlq({ owner_user_id: request.auth.user.id, workspace_id: args.project || null, run_id: args.run_id || null, request_id: request.requestId, component: "colab", stage: name, prompt: args.prompt || args.message || "", attempts: error.attempts || [], error: { type: error.name, message: error.message, retriable: true } });
      response.status(status).json({ ok: false, error: error.message, request_id: request.requestId });
    }
  });

  io.use((socket, next) => { const context = auth.authenticate(socket.request); if (!context) return next(new Error("Authentication required")); socket.data.auth = context; next(); });
  io.on("connection", (socket) => {
    const user = socket.data.auth.user; socket.join(`user:${user.id}`); if (user.role === "admin") socket.join("role:admin"); socket.emit("connection:ready", { user }); terminal.register(socket);
    socket.on("workspace:join", (data = {}) => { try { const project = String(data.project || ""); safeWorkspacePath(config.workspaceRoot, project); if (!auth.canAccess(user, project)) throw new Error("Workspace access denied"); socket.join(`workspace:${project}`); socket.emit("workspace:ready", { project }); } catch (error) { socket.emit("workspace:error", { message: error.message }); } });
    socket.on("workspace:leave", (data = {}) => { const project = String(data.project || ""); if (project) socket.leave(`workspace:${project}`); });
    socket.on("editor:change", (data = {}) => { try { const project = String(data.project || ""); const filePath = String(data.path || ""); if (!auth.canAccess(user, project)) throw new Error("Workspace access denied"); safeWorkspacePath(config.workspaceRoot, project, filePath); socket.to(`workspace:${project}`).emit("editor:change", { project, path: filePath, content: String(data.content || ""), clientId: String(data.clientId || ""), version: Number(data.version || 0) }); } catch (error) { socket.emit("workspace:error", { message: error.message }); } });
  });

  if (fs.existsSync(config.frontendDist)) app.use(express.static(config.frontendDist, { index: false }));
  app.use((request, response) => { if (request.path.startsWith("/api/")) return response.status(404).json({ ok: false, error: "API route not found" }); if (path.extname(request.path)) return response.status(404).send("Asset not found"); const indexPath = path.join(config.frontendDist, "index.html"); if (!fs.existsSync(indexPath)) return response.status(503).type("text").send("Frontend build not found. Run: npm run build"); return response.sendFile(indexPath); });
  async function close() { terminal.close(); lsp.close(); await watcher.close(); await mcp.close(); io.close(); }
  return { app, server, io, mcp, close, getConfig: () => config, auth, dev };
}
