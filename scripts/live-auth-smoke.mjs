import { io } from "socket.io-client";

const base = process.env.BOB_URL || "http://127.0.0.1:3000";
const username = process.env.BOB_SMOKE_USERNAME || "";
const password = process.env.BOB_SMOKE_PASSWORD || "";
if (!username || !password) throw new Error("BOB_SMOKE_USERNAME and BOB_SMOKE_PASSWORD are required");

function timeout(message, milliseconds = 20000) {
  return new Promise((_, reject) => setTimeout(() => reject(new Error(message)), milliseconds));
}

async function api(path, { method = "GET", cookie = "", csrf = "", body } = {}) {
  const response = await fetch(`${base}${path}`, {
    method,
    headers: {
      ...(body ? { "content-type": "application/json" } : {}),
      ...(cookie ? { cookie } : {}),
      ...(csrf ? { "x-csrf-token": csrf } : {}),
    },
    body: body ? JSON.stringify(body) : undefined,
  });
  const payload = await response.json();
  if (!response.ok || !payload.ok) throw new Error(`${path} failed: HTTP ${response.status} ${payload.error || "unknown error"}`);
  return { response, payload };
}

const login = await api("/api/auth/login", { method: "POST", body: { username, password } });
const cookie = login.response.headers.get("set-cookie")?.split(";", 1)[0] || "";
const csrf = login.payload.data.csrf_token;
if (!cookie || !csrf) throw new Error("Login did not return a session cookie and CSRF token");

const health = await api("/api/health", { cookie });
if (!health.payload.data.python || !health.payload.data.frontendBuilt) throw new Error("Gateway dependencies are not healthy");

const workspace = await api("/api/mcp/call", {
  method: "POST",
  cookie,
  csrf,
  body: { name: "workspace.list", arguments: {} },
});
const projects = workspace.payload.data.projects || [];
const project = projects.includes("sample_project") ? "sample_project" : projects[0];
if (!project) throw new Error("No project is available for the terminal smoke test");

const status = await api("/api/mcp/call", {
  method: "POST",
  cookie,
  csrf,
  body: { name: "system.status", arguments: {} },
});
if (status.payload.data.service !== "Bob IDE") throw new Error("Authenticated MCP call returned an unexpected service");

const socket = io(base, { transports: ["websocket"], extraHeaders: { Cookie: cookie } });
let output = "";
try {
  await Promise.race([
    new Promise((resolve, reject) => {
      socket.once("connect", resolve);
      socket.once("connect_error", reject);
    }),
    timeout("Authenticated WebSocket connection timed out"),
  ]);
  const terminalId = "production-smoke";
  const completed = new Promise((resolve, reject) => {
    socket.on("terminal:data", (event) => {
      if (event.terminalId !== terminalId) return;
      output += event.data;
      if (output.includes(`BOB_TERMINAL_OK:${project}:Python`)) resolve();
    });
    socket.on("terminal:error", (event) => {
      if (event.terminalId === terminalId) reject(new Error(event.message));
    });
    socket.on("terminal:ready", (event) => {
      if (event.terminalId !== terminalId) return;
      if (event.project !== project || event.cwd !== `/${project}` || !event.sandboxed) {
        reject(new Error(`Unexpected terminal identity: ${JSON.stringify(event)}`));
        return;
      }
      socket.emit("terminal:input", {
        terminalId,
        data: `printf 'BOB_TERMINAL_OK:%s:' "$BOB_ACTIVE_PROJECT"; python --version 2>&1\r`,
      });
    });
  });
  socket.emit("terminal:create", { terminalId, project });
  await Promise.race([completed, timeout("Sandboxed terminal smoke test timed out", 30000)]);
  socket.emit("terminal:dispose", { terminalId });
} finally {
  socket.close();
}

console.log(`Authenticated production smoke passed: health, MCP, WebSocket, terminal container, Python; project=${project}`);
