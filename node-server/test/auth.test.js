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
  const { root, instance } = fixture(); const agent = request.agent(instance.app);
  try {
    assert.equal((await agent.get("/api/auth/status")).body.data.setup_required, true);
    assert.equal((await agent.get("/api/config")).status, 401);
    const setup = await agent.post("/api/auth/setup").set("X-Forwarded-For", "127.0.0.1").send({ username: "admin", display_name: "Admin User", password: "correct-horse-battery" });
    assert.equal(setup.status, 201); assert.equal(setup.body.data.user.role, "admin"); assert.ok(setup.headers["set-cookie"][0].includes("HttpOnly"));
    const usersFile = JSON.parse(fs.readFileSync(path.join(root, "data", "auth", "users.json"), "utf8"));
    assert.match(usersFile.users[0].password_hash, /^\$2[aby]\$12\$/); assert.equal(usersFile.users[0].password, undefined);
    assert.equal((await agent.post("/api/auth/setup").send({ username: "other", display_name: "Other", password: "correct-horse-battery" })).status, 409);
    const me = await agent.get("/api/auth/me"); assert.equal(me.status, 200); const csrf = me.body.data.csrf_token;
    assert.equal((await agent.post("/api/auth/logout").send({})).status, 403);
    assert.equal((await agent.post("/api/auth/logout").set("X-CSRF-Token", csrf).send({})).status, 200);
    assert.equal((await agent.get("/api/auth/me")).status, 401);
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
