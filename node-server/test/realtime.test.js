import assert from "node:assert/strict";
import test from "node:test";
import { io as createClient } from "socket.io-client";
import { createServer } from "../server.js";

function once(socket, event) {
  return new Promise((resolve, reject) => {
    const timer = setTimeout(() => reject(new Error(`Timed out waiting for ${event}`)), 5000);
    socket.once(event, (payload) => {
      clearTimeout(timer);
      resolve(payload);
    });
  });
}

test("workspace rooms relay editor changes without echoing to the sender", async () => {
  const instance = createServer();
  await new Promise((resolve) => instance.server.listen(0, "127.0.0.1", resolve));
  const { port } = instance.server.address();
  const first = createClient(`http://127.0.0.1:${port}`, { transports: ["websocket"] });
  const second = createClient(`http://127.0.0.1:${port}`, { transports: ["websocket"] });
  try {
    await Promise.all([once(first, "connect"), once(second, "connect")]);
    first.emit("workspace:join", { project: "sample_project" });
    second.emit("workspace:join", { project: "sample_project" });
    await Promise.all([once(first, "workspace:ready"), once(second, "workspace:ready")]);
    const received = once(second, "editor:change");
    first.emit("editor:change", {
      project: "sample_project",
      path: "app.py",
      content: "print('live')",
      clientId: "first",
      version: 1,
    });
    const event = await received;
    assert.equal(event.content, "print('live')");
    assert.equal(event.clientId, "first");
  } finally {
    first.close();
    second.close();
    await instance.close();
    await new Promise((resolve) => instance.server.close(resolve));
  }
});
