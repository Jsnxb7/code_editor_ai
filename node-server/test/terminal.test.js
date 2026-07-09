import assert from "node:assert/strict";
import test from "node:test";
import { readConfig } from "../config.js";
import { TerminalManager } from "../terminal.js";

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
  const sessions = [];
  const emitted = [];
  const socket = {
    id: "socket-1",
    emit: (event, payload) => emitted.push({ event, payload }),
  };
  const manager = new TerminalManager({
    workspaceRoot: readConfig().workspaceRoot,
    ptyModule: {
      spawn: () => {
        const session = new FakePty();
        sessions.push(session);
        return session;
      },
    },
  });

  manager.create(socket, { terminalId: "terminal-1", project: "sample_project" });
  manager.create(socket, { terminalId: "terminal-1", project: "sample_project" });

  assert.equal(emitted.filter((item) => item.event === "terminal:exit").length, 0);
  assert.equal(manager.sessions.size, 1);

  sessions[1].exitCallback();
  assert.equal(emitted.filter((item) => item.event === "terminal:exit").length, 1);
  assert.equal(manager.sessions.size, 0);
});
