import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import test from "node:test";
import request from "supertest";
import { createServer } from "../server.js";

function fixture() {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), "bob-auth-"));
  const workspaceRoot = path.join(root, "workspace"); fs.mkdirSync(path.join(workspaceRoot, "legacy"), { recursive: true });
  return { root, workspaceRoot, instance: createServer({ dataRoot: path.join(root, "data"), workspaceRoot }) };
}

test("first-run setup creates a hashed admin session and protects API routes", async () => {
  const { root, workspaceRoot, instance } = fixture(); const agent = request.agent(instance.app);
  try {
    assert.equal((await agent.get("/api/auth/status")).body.data.setup_required, true);
    assert.equal((await agent.get("/api/config")).status, 401);
    const setup = await agent.post("/api/auth/setup").set("X-Forwarded-For", "127.0.0.1").send({ username: "admin", display_name: "Admin User", password: "correct-horse-battery" });
    assert.equal(setup.status, 201); assert.equal(setup.body.data.user.role, "admin"); assert.ok(setup.headers["set-cookie"][0].includes("HttpOnly"));
    const adminDirectory = instance.auth.userDirectory(setup.body.data.user);
    assert.equal(fs.existsSync(path.join(workspaceRoot, "legacy")), false);
    assert.equal(fs.existsSync(path.join(workspaceRoot, adminDirectory, "legacy")), true);
    const usersFile = JSON.parse(fs.readFileSync(path.join(root, "data", "auth", "users.json"), "utf8"));
    assert.match(usersFile.users[0].password_hash, /^\$2[aby]\$12\$/); assert.equal(usersFile.users[0].password, undefined);
    assert.equal((await agent.post("/api/auth/setup").send({ username: "other", display_name: "Other", password: "correct-horse-battery" })).status, 409);
    const me = await agent.get("/api/auth/me"); assert.equal(me.status, 200); const csrf = me.body.data.csrf_token;
    assert.equal((await agent.post("/api/auth/logout").send({})).status, 403);
    assert.equal((await agent.post("/api/auth/logout").set("X-CSRF-Token", csrf).send({})).status, 200);
    assert.equal((await agent.get("/api/auth/me")).status, 401);
    const httpLogs = instance.dev.logs({ type: "http.request" });
    assert.ok(httpLogs.length >= 1); assert.ok(httpLogs.every((item) => item.request_id));
    assert.ok(httpLogs.some((item) => item.status === 401));
  } finally { await instance.close(); fs.rmSync(root, { recursive: true, force: true }); }
});

test("one-time approvals are owner, operation, target, and expiry bound", async () => {
  const { root, instance } = fixture();
  try {
    const setup = await instance.auth.setup({ username: "admin", display_name: "Admin User", password: "correct-horse-battery" }); const user = setup.user;
    const issued = instance.auth.issueApproval(user, { operation: "proposal.override_apply", project: "legacy", target: "proposal_1", reason: "Reviewed failure" });
    const consumed = instance.auth.consumeApproval(user, issued.approval_token, { operation: "proposal.override_apply", project: "legacy", target: "proposal_1" }); assert.ok(consumed.consumed_at);
    assert.throws(() => instance.auth.consumeApproval(user, issued.approval_token, { operation: "proposal.override_apply", project: "legacy", target: "proposal_1" }), /Valid one-time approval/);
  } finally { await instance.close(); fs.rmSync(root, { recursive: true, force: true }); }
});

test("login failures are limited independently by client address", async () => {
  const { root, instance } = fixture();
  try {
    await instance.auth.setup({ username: "admin", display_name: "Admin User", password: "correct-horse-battery" });
    for (let index = 0; index < 5; index += 1) await assert.rejects(instance.auth.login(`missing${index}`, "wrong", { ip: "10.1.2.3" }), /Invalid username or password/);
    await assert.rejects(instance.auth.login("another-user", "wrong", { ip: "10.1.2.3" }), (error) => error.status === 429);
  } finally { await instance.close(); fs.rmSync(root, { recursive: true, force: true }); }
});

test("concurrent first-run setup creates exactly one administrator", async () => {
  const { root, instance } = fixture();
  try {
    const results = await Promise.allSettled([
      instance.auth.setup({ username: "admin-one", display_name: "Admin One", password: "correct-horse-battery" }),
      instance.auth.setup({ username: "admin-two", display_name: "Admin Two", password: "correct-horse-battery" }),
    ]);
    assert.equal(results.filter((item) => item.status === "fulfilled").length, 1);
    assert.equal(instance.auth.listUsers().length, 1);
  } finally { await instance.close(); fs.rmSync(root, { recursive: true, force: true }); }
});

test("parallel MCP callers receive server-bound identities and separate workspace authorization", async () => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), "bob-mcp-users-"));
  const workspaceRoot = path.join(root, "workspace");
  fs.mkdirSync(path.join(workspaceRoot, "admin-workspace"), { recursive: true });
  fs.mkdirSync(path.join(workspaceRoot, "user-workspace"), { recursive: true });
  const instance = createServer({ dataRoot: path.join(root, "data"), workspaceRoot });
  const adminAgent = request.agent(instance.app);
  const userAgent = request.agent(instance.app);
  try {
    const setup = await adminAgent.post("/api/auth/setup").send({ username: "admin", display_name: "Admin User", password: "correct-horse-battery" });
    const admin = setup.body.data.user;
    const regular = await instance.auth.createUser({ username: "worker", display_name: "Worker User", password: "correct-horse-battery", role: "user" }, admin);
    instance.auth.assignOwner("user-workspace", regular.id, admin);
    const login = await userAgent.post("/api/auth/login").send({ username: "worker", password: "correct-horse-battery" });
    const calls = [];
    instance.mcp.callTool = async (name, args) => {
      calls.push({ name, args: structuredClone(args) });
      await new Promise((resolve) => setTimeout(resolve, 10));
      return { status: "idle" };
    };

    const [adminStatus, userStatus] = await Promise.all([
      adminAgent.post("/api/mcp/call").set("X-CSRF-Token", setup.body.data.csrf_token).send({ name: "model.queue_status", arguments: { actor_user_id: "spoofed" } }),
      userAgent.post("/api/mcp/call").set("X-CSRF-Token", login.body.data.csrf_token).send({ name: "model.queue_status", arguments: { actor_user_id: admin.id } }),
    ]);
    assert.equal(adminStatus.status, 200);
    assert.equal(userStatus.status, 200);
    assert.deepEqual(new Set(calls.map((item) => item.args.actor_user_id)), new Set([admin.id, regular.id]));

    await Promise.all([
      adminAgent.post("/api/mcp/call").set("X-CSRF-Token", setup.body.data.csrf_token).send({ name: "workspace.list", arguments: {} }),
      userAgent.post("/api/mcp/call").set("X-CSRF-Token", login.body.data.csrf_token).send({ name: "workspace.tree", arguments: { project: "user-workspace" } }),
    ]);
    assert.equal(calls[2].args.scope, instance.auth.userDirectory(admin));
    assert.equal(calls[3].args.project, instance.auth.projectRef(regular, "user-workspace"));

    const denied = await userAgent.post("/api/mcp/call").set("X-CSRF-Token", login.body.data.csrf_token).send({ name: "terminal.execute", arguments: { project: "admin-workspace", command: "echo no" } });
    assert.equal(denied.status, 403);
    assert.equal(calls.length, 4);
  } finally {
    await instance.close();
    fs.rmSync(root, { recursive: true, force: true });
  }
});
