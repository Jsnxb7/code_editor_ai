import fs from "node:fs";
import path from "node:path";
import { spawnSync } from "node:child_process";
import { fileURLToPath } from "node:url";
import { findPython } from "./python-command.mjs";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const apiSource = fs.readFileSync(path.join(root, "frontend", "src", "api.js"), "utf8");
const frontendTools = new Set(
  [...apiSource.matchAll(/invoke\("([^"]+)"/g)].map((match) => match[1]),
);
const python = findPython(root);
const result = spawnSync(
  python.command,
  [...python.prefix, "-c", "import json; from capabilities import CAPABILITIES; print(json.dumps(sorted(CAPABILITIES)))"],
  { cwd: root, encoding: "utf8" },
);
if (result.status !== 0) {
  console.error(result.stderr || "Unable to load Python capabilities.");
  process.exit(result.status || 1);
}
const pythonTools = new Set(JSON.parse(result.stdout.trim()));
const missing = [...frontendTools].filter((name) => !pythonTools.has(name)).sort();
if (missing.length) {
  console.error(`Frontend MCP tools missing from Python: ${missing.join(", ")}`);
  process.exit(1);
}
console.log(`API contract verified: ${frontendTools.size} frontend tools, ${pythonTools.size} Python tools.`);
