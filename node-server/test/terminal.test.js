import assert from "node:assert/strict";
import test from "node:test";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { spawnSync } from "node:child_process";
import { fileURLToPath } from "node:url";
import { TerminalManager } from "../terminal.js";

const terminalInitPath = path.join(path.dirname(fileURLToPath(import.meta.url)), "..", "terminal-init.sh");

class FakePty {
  onData(callback) {
    this.dataCallback = callback;
  }

  onExit(callback) {
    this.exitCallback = callback;
  }

  write() {}
  resize() {}

  kill() {
    this.exitCallback?.();
  }
}

test("replacing a terminal ignores the old session exit callback", () => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), "bob-terminal-"));
  const workspaceRoot = path.join(root, "workspace");
  const userRoot = path.join(workspaceRoot, "admin--user-one");
  fs.mkdirSync(path.join(userRoot, "sample_project"), { recursive: true });
  const sessions = [];
  const spawnOptions = [];
  const emitted = [];
  const socket = {
    id: "socket-1",
    data: { auth: { user: { id: "user-one", username: "admin", role: "admin" } }, requestId: "request-one" },
    emit: (event, payload) => emitted.push({ event, payload }),
  };
  const manager = new TerminalManager({
    workspaceRoot,
    sandboxImage: "bob-terminal:latest",
    resolveWorkspace: () => ({ projectRef: "admin--user-one/sample_project", userRoot, user: socket.data.auth.user }),
    ptyModule: {
      spawn: (_shell, _args, options) => {
        const session = new FakePty();
        sessions.push(session);
        spawnOptions.push(options);
        return session;
      },
    },
  });
  try {
    manager.create(socket, { terminalId: "terminal-1", project: "sample_project" });
    manager.create(socket, { terminalId: "terminal-1", project: "sample_project" });

    assert.equal(emitted.filter((item) => item.event === "terminal:exit").length, 0);
    assert.equal(manager.sessions.size, 1);
    assert.equal(spawnOptions[1].env.BOB_USER_ID, "user-one");
    assert.match(spawnOptions[1].env.HOME, /\.bob[\\/]runtime[\\/]user-one$/);
    assert.equal(spawnOptions[1].env.BOB_COLAB_TOKEN, undefined);

    sessions[1].exitCallback();
    assert.equal(emitted.filter((item) => item.event === "terminal:exit").length, 1);
    assert.equal(manager.sessions.size, 0);
  } finally {
    manager.close();
    fs.rmSync(root, { recursive: true, force: true });
  }
});

test("all terminals require a container, mount only the user root, and start in the active project", () => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), "bob-terminal-sandbox-"));
  const workspaceRoot = path.join(root, "workspace");
  const userRoot = path.join(workspaceRoot, "worker--user-two");
  fs.mkdirSync(path.join(userRoot, "same-name"), { recursive: true });
  fs.mkdirSync(path.join(userRoot, "second-project"), { recursive: true });
  const emitted = [];
  const socket = { id: "socket-2", data: { auth: { user: { id: "user-two", username: "worker", role: "user" } } }, emit: (event, payload) => emitted.push({ event, payload }) };
  const spawned = [];
  const ptyModule = { spawn: (shell, args, options) => { const session = new FakePty(); spawned.push({ shell, args, options, session }); return session; } };
  const resolveWorkspace = () => ({ projectRef: "worker--user-two/same-name", userRoot, user: socket.data.auth.user });
  try {
    const denied = new TerminalManager({ workspaceRoot, ptyModule, resolveWorkspace });
    denied.create(socket, { terminalId: "denied", project: "same-name" });
    assert.match(emitted.at(-1).payload.message, /container terminal is required/i);
    assert.equal(spawned.length, 0);

    const sandboxed = new TerminalManager({ workspaceRoot, ptyModule, resolveWorkspace, sandboxImage: "bob-terminal:latest" });
    sandboxed.create(socket, { terminalId: "sandboxed", project: "same-name" });
    assert.equal(spawned[0].shell, "docker");
    const projectRoot = path.join(userRoot, "same-name");
    assert.ok(spawned[0].args.includes(`type=bind,source=${userRoot},target=/workspace`));
    assert.equal(spawned[0].args.includes(`type=bind,source=${projectRoot},target=/workspace`), false);
    assert.ok(spawned[0].args.some((value) => String(value).includes("target=/etc/bob-terminal-init.sh,readonly")));
    assert.ok(spawned[0].args.includes("BOB_TERMINAL_ROOT=/workspace"));
    assert.ok(spawned[0].args.includes("BOB_TERMINAL_START=/workspace/same-name"));
    assert.ok(spawned[0].args.includes("BOB_WORKSPACE=/workspace/same-name"));
    assert.ok(spawned[0].args.includes("BOB_ACTIVE_PROJECT=same-name"));
    assert.ok(spawned[0].args.includes("HOME=/workspace/.bob/runtime/user-two"));
    assert.equal(spawned[0].args.some((value) => String(value).includes("admin--")), false);
    assert.equal(spawned[0].args[spawned[0].args.indexOf("-w") + 1], "/workspace/same-name");
    assert.equal(spawned[0].options.env.HOME, path.join(userRoot, ".bob", "runtime", "user-two"));
    assert.equal(emitted.at(-1).payload.cwd, "/same-name");
    assert.equal(emitted.at(-1).payload.project, "same-name");
    assert.equal(emitted.at(-1).payload.sandboxed, true);
    sandboxed.close();
  } finally {
    fs.rmSync(root, { recursive: true, force: true });
  }
});

test("terminal shell starts in the active project, permits sibling projects, and cannot leave the user root", { skip: process.platform === "win32" }, () => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), "bob-terminal-root-"));
  fs.mkdirSync(path.join(root, "project-a"));
  fs.mkdirSync(path.join(root, "project-b"));
  try {
    const command = 'printf "start=%s\\n" "$PWD"; cd ..; printf "user-root=%s\\n" "$PWD"; cd project-b; __bob_terminal_prompt; printf "prompt=%s\\n" "$PS1"; cd ../..; printf "after-denied=%s\\n" "$PWD"';
    const result = spawnSync("/bin/bash", ["--noprofile", "--rcfile", terminalInitPath, "-ic", command], {
      env: { ...process.env, BOB_TERMINAL_ROOT: root, BOB_TERMINAL_START: path.join(root, "project-a") },
      encoding: "utf8",
    });
    assert.equal(result.status, 0, result.stderr);
    assert.match(result.stderr, /Access denied: the terminal cannot leave your user workspace\./);
    const escapedRoot = root.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
    assert.match(result.stdout, new RegExp(`start=${escapedRoot}[/\\\\]project-a`));
    assert.match(result.stdout, new RegExp(`user-root=${escapedRoot}`));
    assert.match(result.stdout, /prompt=bob:\/project-b\\\$ /);
    assert.match(result.stdout, new RegExp(`after-denied=${escapedRoot}[/\\\\]project-b`));
  } finally {
    fs.rmSync(root, { recursive: true, force: true });
  }
});

test("terminal image provides python, pip, and venv support", () => {
  const dockerfile = fs.readFileSync(path.join(path.dirname(terminalInitPath), "terminal.Dockerfile"), "utf8");
  assert.match(dockerfile, /python3-pip/);
  assert.match(dockerfile, /python3-venv/);
  assert.match(dockerfile, /python-is-python3/);
});

test("terminal rejects a project that does not belong to the resolved user root", () => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), "bob-terminal-cross-user-"));
  const workspaceRoot = path.join(root, "workspace");
  const userRoot = path.join(workspaceRoot, "worker--user-one");
  fs.mkdirSync(path.join(userRoot, "own-project"), { recursive: true });
  fs.mkdirSync(path.join(workspaceRoot, "other--user-two", "private-project"), { recursive: true });
  const emitted = [];
  let spawned = false;
  const socket = { id: "socket-cross-user", data: { auth: { user: { id: "user-one", username: "worker", role: "user" } } }, emit: (event, payload) => emitted.push({ event, payload }) };
  const manager = new TerminalManager({
    workspaceRoot,
    sandboxImage: "bob-terminal:latest",
    resolveWorkspace: () => ({ projectRef: "other--user-two/private-project", userRoot, user: socket.data.auth.user }),
    ptyModule: { spawn: () => { spawned = true; return new FakePty(); } },
  });
  try {
    manager.create(socket, { terminalId: "blocked", project: "private-project" });
    assert.equal(spawned, false);
    assert.equal(emitted.at(-1).event, "terminal:error");
    assert.match(emitted.at(-1).payload.message, /escapes user workspace root/i);
  } finally {
    manager.close();
    fs.rmSync(root, { recursive: true, force: true });
  }
});
