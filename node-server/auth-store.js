import crypto from "node:crypto";
import fs from "node:fs";
import path from "node:path";
import bcrypt from "bcryptjs";

const SCHEMA_VERSION = "1.0";
const COOKIE_NAME = "bob_session";
const IDLE_MS = 8 * 60 * 60 * 1000;
const MAX_MS = 24 * 60 * 60 * 1000;
const LOGIN_WINDOW_MS = 15 * 60 * 1000;
const LOGIN_LIMIT = 5;

function iso(value = Date.now()) { return new Date(value).toISOString(); }
function hash(value) { return crypto.createHash("sha256").update(String(value)).digest("hex"); }
function token() { return crypto.randomBytes(32).toString("base64url"); }
function normalizeUsername(value) { return String(value || "").trim().toLowerCase(); }
function readJson(file, fallback) {
  try { return JSON.parse(fs.readFileSync(file, "utf8")); }
  catch (error) { if (error.code === "ENOENT") return structuredClone(fallback); throw error; }
}
function writeJson(file, value) {
  fs.mkdirSync(path.dirname(file), { recursive: true });
  const temporary = `${file}.${process.pid}.${Date.now()}.tmp`;
  fs.writeFileSync(temporary, `${JSON.stringify(value, null, 2)}\n`, "utf8");
  fs.renameSync(temporary, file);
}
function cookieMap(header = "") {
  return Object.fromEntries(String(header).split(";").map((part) => part.trim()).filter(Boolean).map((part) => {
    const index = part.indexOf("=");
    return [decodeURIComponent(index < 0 ? part : part.slice(0, index)), decodeURIComponent(index < 0 ? "" : part.slice(index + 1))];
  }));
}
function publicUser(user) {
  return user && { id: user.id, username: user.username, display_name: user.display_name, role: user.role, enabled: user.enabled, created_at: user.created_at, updated_at: user.updated_at };
}

export class AuthStore {
  constructor({ dataRoot, workspaceRoot, audit }) {
    this.root = path.join(dataRoot, "auth");
    this.usersPath = path.join(this.root, "users.json");
    this.sessionsPath = path.join(this.root, "sessions.json");
    this.ownersPath = path.join(this.root, "workspace-owners.json");
    this.approvalsPath = path.join(this.root, "approvals.json");
    this.workspaceRoot = workspaceRoot;
    this.audit = audit;
    this.failures = new Map();
    this.setupPending = false;
  }

  usersData() { return readJson(this.usersPath, { schema_version: SCHEMA_VERSION, users: [] }); }
  sessionsData() { return readJson(this.sessionsPath, { schema_version: SCHEMA_VERSION, sessions: [] }); }
  ownersData() { return readJson(this.ownersPath, { schema_version: SCHEMA_VERSION, owners: {} }); }
  approvalsData() { return readJson(this.approvalsPath, { schema_version: SCHEMA_VERSION, approvals: [] }); }
  status() { return { setup_required: this.usersData().users.length === 0 }; }

  validateAccount({ username, display_name: displayName, password }) {
    const normalized = normalizeUsername(username);
    if (!/^[a-z0-9][a-z0-9._-]{2,31}$/.test(normalized)) throw new Error("Username must be 3-32 characters using letters, numbers, dot, underscore, or hyphen");
    if (String(displayName || "").trim().length < 2) throw new Error("Display name must contain at least 2 characters");
    if (String(password || "").length < 12) throw new Error("Password must contain at least 12 characters");
    return normalized;
  }

  async setup(payload, requestMeta = {}) {
    if (this.setupPending || this.usersData().users.length) throw Object.assign(new Error("Initial setup is already complete"), { status: 409 });
    this.setupPending = true;
    try {
      const username = this.validateAccount(payload);
      const passwordHash = await bcrypt.hash(String(payload.password), 12);
      const data = this.usersData();
      if (data.users.length) throw Object.assign(new Error("Initial setup is already complete"), { status: 409 });
      const now = iso();
      const user = { id: crypto.randomUUID(), username, display_name: String(payload.display_name).trim(), role: "admin", password_hash: passwordHash, enabled: true, created_at: now, updated_at: now };
      data.users.push(user);
      writeJson(this.usersPath, data);
      const owners = this.ownersData();
      if (fs.existsSync(this.workspaceRoot)) {
        for (const item of fs.readdirSync(this.workspaceRoot, { withFileTypes: true })) if (item.isDirectory() && !owners.owners[item.name]) owners.owners[item.name] = user.id;
      }
      writeJson(this.ownersPath, owners);
      this.audit?.("auth.setup", { actor_user_id: user.id, assigned_workspaces: Object.keys(owners.owners), ...requestMeta });
      return { user: publicUser(user), ...this.createSession(user, requestMeta) };
    } finally { this.setupPending = false; }
  }

  failureKeys(username, ip) { return [`username:${normalizeUsername(username)}`, `address:${ip || "local"}`]; }
  checkRate(username, ip) {
    const cutoff = Date.now() - LOGIN_WINDOW_MS;
    for (const key of this.failureKeys(username, ip)) {
      const attempts = (this.failures.get(key) || []).filter((value) => value > cutoff);
      this.failures.set(key, attempts);
      if (attempts.length >= LOGIN_LIMIT) throw Object.assign(new Error("Invalid username or password"), { status: 429 });
    }
  }
  recordFailure(username, ip) { for (const key of this.failureKeys(username, ip)) this.failures.set(key, [...(this.failures.get(key) || []), Date.now()]); }

  async login(usernameValue, password, requestMeta = {}) {
    const username = normalizeUsername(usernameValue); this.checkRate(username, requestMeta.ip);
    const user = this.usersData().users.find((item) => item.username === username);
    const valid = Boolean(user?.enabled) && await bcrypt.compare(String(password || ""), user.password_hash || "");
    if (!valid) { this.recordFailure(username, requestMeta.ip); this.audit?.("auth.login_failed", { username, ...requestMeta }); throw Object.assign(new Error("Invalid username or password"), { status: 401 }); }
    for (const key of this.failureKeys(username, requestMeta.ip)) this.failures.delete(key);
    const session = this.createSession(user, requestMeta);
    this.audit?.("auth.login", { actor_user_id: user.id, session_id: session.session_id, ...requestMeta });
    return { user: publicUser(user), ...session };
  }

  createSession(user, requestMeta = {}) {
    const rawToken = token(); const csrfToken = token(); const now = Date.now();
    const data = this.pruneSessions(this.sessionsData());
    const record = { id: crypto.randomUUID(), token_hash: hash(rawToken), csrf_hash: hash(csrfToken), user_id: user.id, created_at: iso(now), last_seen_at: iso(now), idle_expires_at: iso(now + IDLE_MS), absolute_expires_at: iso(now + MAX_MS), ip: requestMeta.ip || null, user_agent: String(requestMeta.user_agent || "").slice(0, 300) };
    data.sessions.push(record); writeJson(this.sessionsPath, data);
    return { session_token: rawToken, csrf_token: csrfToken, session_id: record.id, expires_at: record.absolute_expires_at };
  }

  pruneSessions(data = this.sessionsData()) {
    const now = Date.now();
    data.sessions = data.sessions.filter((item) => Date.parse(item.idle_expires_at) > now && Date.parse(item.absolute_expires_at) > now);
    return data;
  }

  authenticate(request) {
    const rawToken = cookieMap(request.headers.cookie)[COOKIE_NAME]; if (!rawToken) return null;
    const data = this.pruneSessions(this.sessionsData()); const tokenHash = hash(rawToken);
    const session = data.sessions.find((item) => crypto.timingSafeEqual(Buffer.from(item.token_hash), Buffer.from(tokenHash)));
    if (!session) { writeJson(this.sessionsPath, data); return null; }
    const users = this.usersData(); const user = users.users.find((item) => item.id === session.user_id && item.enabled);
    if (!user) return null;
    const now = Date.now();
    if (now - Date.parse(session.last_seen_at) > 5 * 60 * 1000) { session.last_seen_at = iso(now); session.idle_expires_at = iso(now + IDLE_MS); writeJson(this.sessionsPath, data); }
    return { user: publicUser(user), session, csrf_token_valid: (value) => Boolean(value) && hash(value) === session.csrf_hash };
  }

  rotateCsrf(sessionId) {
    const data = this.sessionsData(); const session = data.sessions.find((item) => item.id === sessionId);
    if (!session) throw Object.assign(new Error("Session not found"), { status: 401 });
    const csrfToken = token(); session.csrf_hash = hash(csrfToken); writeJson(this.sessionsPath, data); return csrfToken;
  }

  logout(rawToken, actor = {}) {
    if (!rawToken) return;
    const data = this.sessionsData(); const tokenHash = hash(rawToken);
    const removed = data.sessions.filter((item) => item.token_hash === tokenHash);
    data.sessions = data.sessions.filter((item) => item.token_hash !== tokenHash); writeJson(this.sessionsPath, data);
    if (removed.length) this.audit?.("auth.logout", { actor_user_id: actor.id, session_id: removed[0].id });
  }

  cookie(rawToken) { return `${COOKIE_NAME}=${encodeURIComponent(rawToken)}; Path=/; HttpOnly; SameSite=Strict; Max-Age=${MAX_MS / 1000}`; }
  clearCookie() { return `${COOKIE_NAME}=; Path=/; HttpOnly; SameSite=Strict; Max-Age=0`; }
  rawCookie(request) { return cookieMap(request.headers.cookie)[COOKIE_NAME] || ""; }
  listUsers() {
    const sessions = this.pruneSessions(this.sessionsData()).sessions;
    return this.usersData().users.map((user) => ({
      ...publicUser(user),
      active_sessions: sessions.filter((item) => item.user_id === user.id).length,
      sessions_revoked: !sessions.some((item) => item.user_id === user.id),
    }));
  }

  async createUser(payload, actor) {
    const username = this.validateAccount(payload); const data = this.usersData();
    if (data.users.some((item) => item.username === username)) throw Object.assign(new Error("Username already exists"), { status: 409 });
    const now = iso(); const role = payload.role === "admin" ? "admin" : "user";
    const user = { id: crypto.randomUUID(), username, display_name: String(payload.display_name).trim(), role, password_hash: await bcrypt.hash(String(payload.password), 12), enabled: true, created_at: now, updated_at: now };
    data.users.push(user); writeJson(this.usersPath, data); this.audit?.("user.created", { actor_user_id: actor.id, target_user_id: user.id, role }); return publicUser(user);
  }

  async updateUser(userId, payload, actor) {
    const data = this.usersData(); const user = data.users.find((item) => item.id === userId); if (!user) throw Object.assign(new Error("User not found"), { status: 404 });
    if (payload.display_name !== undefined) { if (String(payload.display_name).trim().length < 2) throw new Error("Display name must contain at least 2 characters"); user.display_name = String(payload.display_name).trim(); }
    if (payload.role !== undefined) user.role = payload.role === "admin" ? "admin" : "user";
    if (payload.enabled !== undefined) user.enabled = Boolean(payload.enabled);
    if (payload.password !== undefined) { if (String(payload.password).length < 12) throw new Error("Password must contain at least 12 characters"); user.password_hash = await bcrypt.hash(String(payload.password), 12); }
    const enabledAdmins = data.users.filter((item) => item.enabled && item.role === "admin" && item.id !== user.id);
    if ((!user.enabled || user.role !== "admin") && actor.id === user.id && !enabledAdmins.length) throw new Error("The last enabled administrator cannot remove their own access");
    user.updated_at = iso(); writeJson(this.usersPath, data);
    if (payload.password !== undefined || payload.enabled === false || payload.role !== undefined) { const sessions = this.sessionsData(); sessions.sessions = sessions.sessions.filter((item) => item.user_id !== user.id); writeJson(this.sessionsPath, sessions); }
    this.audit?.("user.updated", { actor_user_id: actor.id, target_user_id: user.id, fields: Object.keys(payload) }); return publicUser(user);
  }

  ownerOf(project) { return this.ownersData().owners[String(project)] || null; }
  canAccess(user, project) { return Boolean(user && project && this.ownerOf(project) === user.id); }
  assignOwner(project, userId, actor) { const data = this.ownersData(); data.owners[String(project)] = userId; writeJson(this.ownersPath, data); this.audit?.("workspace.owner_assigned", { actor_user_id: actor?.id || userId, target_user_id: userId, project }); }
  projectsFor(user, projects) { return projects.filter((project) => this.canAccess(user, project)); }

  issueApproval(user, { operation, project, target, reason }) {
    if (!operation || !project || !String(reason || "").trim()) throw new Error("Operation, project, and reason are required");
    if (!this.canAccess(user, project)) throw Object.assign(new Error("Workspace access denied"), { status: 403 });
    const raw = token(); const now = Date.now(); const data = this.approvalsData();
    data.approvals = data.approvals.filter((item) => !item.consumed_at && Date.parse(item.expires_at) > now);
    const item = { id: crypto.randomUUID(), token_hash: hash(raw), user_id: user.id, operation, project, target: target || null, reason: String(reason).trim().slice(0, 1000), created_at: iso(now), expires_at: iso(now + 60_000), consumed_at: null };
    data.approvals.push(item); writeJson(this.approvalsPath, data); this.audit?.("approval.issued", { actor_user_id: user.id, approval_id: item.id, operation, project, target });
    return { approval_token: raw, approval_id: item.id, expires_at: item.expires_at };
  }

  consumeApproval(user, raw, { operation, project, target }) {
    const data = this.approvalsData(); const item = data.approvals.find((value) => value.token_hash === hash(raw || ""));
    if (!item || item.consumed_at || Date.parse(item.expires_at) <= Date.now() || item.user_id !== user.id || item.operation !== operation || item.project !== project || String(item.target || "") !== String(target || "")) throw Object.assign(new Error("Valid one-time approval required"), { status: 403 });
    item.consumed_at = iso(); writeJson(this.approvalsPath, data); this.audit?.("approval.consumed", { actor_user_id: user.id, approval_id: item.id, operation, project, target }); return item;
  }
}

export { COOKIE_NAME, publicUser };
