import { io } from "socket.io-client";

const base = process.env.BOB_URL || "http://127.0.0.1:3000";
const project = process.env.BOB_SMOKE_PROJECT || "sample_project";

function timeout(message, milliseconds = 10000) {
  return new Promise((_, reject) => setTimeout(() => reject(new Error(message)), milliseconds));
}

async function checkHttp() {
  const health = await fetch(`${base}/api/health`).then((response) => response.json());
  if (!health.ok) throw new Error(`Gateway health failed: ${JSON.stringify(health)}`);
  const tools = await fetch(`${base}/api/mcp/tools`).then((response) => response.json());
  if (!tools.ok || !tools.data.tools.includes("worktree.status")) {
    throw new Error("MCP tool discovery failed");
  }
  const status = await fetch(`${base}/api/mcp/call`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ name: "system.status", arguments: {} }),
  }).then((response) => response.json());
  if (!status.ok || status.data.service !== "Bob IDE") throw new Error("MCP call failed");
  const frontend = await fetch(`${base}/editor/smoke`);
  if (!frontend.ok || !(await frontend.text()).includes('<div id="root">')) {
    throw new Error("React SPA fallback failed");
  }
  return tools.data.tools.length;
}

async function checkTerminal() {
  const socket = io(base, { transports: ["websocket"] });
  try {
    await Promise.race([
      new Promise((resolve) => socket.once("connect", resolve)),
      timeout("Terminal socket connection timed out"),
    ]);
    let output = "";
    const complete = new Promise((resolve, reject) => {
      socket.on("terminal:data", (event) => {
        output += event.data;
        if (output.includes("BOB_TERMINAL_OK")) resolve();
      });
      socket.on("terminal:error", (event) => reject(new Error(event.message)));
      socket.once("terminal:ready", () => {
        socket.emit("terminal:input", {
          terminalId: "smoke",
          data: "echo BOB_TERMINAL_OK\r",
        });
      });
    });
    socket.emit("terminal:create", { terminalId: "smoke", project });
    await Promise.race([complete, timeout("Terminal output timed out")]);
    socket.emit("terminal:dispose", { terminalId: "smoke" });
  } finally {
    socket.close();
  }
}

async function checkLsp() {
  const socket = io(`${base}/lsp`, { transports: ["websocket"] });
  try {
    await Promise.race([
      new Promise((resolve) => socket.once("connect", resolve)),
      timeout("LSP socket connection timed out"),
    ]);
    const ready = new Promise((resolve) => socket.once("lsp:ready", resolve));
    socket.emit("lsp:join", { project });
    await Promise.race([ready, timeout("LSP ready timed out")]);
    const initialized = new Promise((resolve) => {
      const onMessage = (message) => {
        if (message.id === 1) {
          socket.off("lsp:message", onMessage);
          resolve(message);
        }
      };
      socket.on("lsp:message", onMessage);
    });
    socket.emit("lsp:message", {
      project,
      message: {
        jsonrpc: "2.0",
        id: 1,
        method: "initialize",
        params: {
          processId: process.pid,
          rootUri: null,
          capabilities: {},
          workspaceFolders: null,
        },
      },
    });
    const response = await Promise.race([initialized, timeout("Pyright initialize timed out")]);
    if (response.error) throw new Error(`Pyright initialize failed: ${response.error.message}`);
  } finally {
    socket.close();
  }
}

const tools = await checkHttp();
await checkTerminal();
await checkLsp();
console.log(`Live smoke passed: React, ${tools} MCP tools, terminal PTY, and Pyright LSP.`);
