import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
export const projectRoot = path.resolve(here, "..");
const configPath = path.join(projectRoot, "data", "node-config.json");

const defaults = {
  host: "127.0.0.1",
  port: 3000,
  mcpUrl: "http://127.0.0.1:8001/mcp",
  mcpTimeoutMs: 120000,
  workspaceRoot: path.join(projectRoot, "workspace"),
  frontendDist: path.join(projectRoot, "frontend", "dist"),
  terminalShell: "",
};

function fromEnvironment(config) {
  return {
    ...config,
    host: process.env.BOB_HOST || config.host,
    port: Number(process.env.BOB_PORT || config.port),
    mcpUrl: process.env.BOB_MCP_URL || config.mcpUrl,
    workspaceRoot: process.env.BOB_WORKSPACE_ROOT || config.workspaceRoot,
    frontendDist: process.env.BOB_FRONTEND_DIST || config.frontendDist,
  };
}

export function readConfig() {
  let stored = {};
  try {
    stored = JSON.parse(fs.readFileSync(configPath, "utf8"));
  } catch (error) {
    if (error.code !== "ENOENT") console.warn("Could not read Node config:", error.message);
  }
  return fromEnvironment({ ...defaults, ...stored });
}

export function writeConfig(updates) {
  const allowed = ["mcpUrl", "mcpTimeoutMs", "terminalShell"];
  const current = readConfig();
  const stored = {};
  for (const key of allowed) {
    if (Object.hasOwn(updates, key)) stored[key] = updates[key];
    else if (current[key] !== defaults[key]) stored[key] = current[key];
  }
  fs.mkdirSync(path.dirname(configPath), { recursive: true });
  const temporary = `${configPath}.tmp`;
  fs.writeFileSync(temporary, `${JSON.stringify(stored, null, 2)}\n`, "utf8");
  fs.renameSync(temporary, configPath);
  return readConfig();
}

export function publicConfig(config = readConfig()) {
  return {
    host: config.host,
    port: config.port,
    mcpUrl: config.mcpUrl,
    mcpTimeoutMs: config.mcpTimeoutMs,
    workspaceRoot: config.workspaceRoot,
    frontendDist: config.frontendDist,
    terminalShell: config.terminalShell,
  };
}
