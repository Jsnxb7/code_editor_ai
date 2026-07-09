import fs from "node:fs";
import path from "node:path";
import { spawnSync } from "node:child_process";

export function findPython(root) {
  const candidates = [];
  if (process.env.BOB_PYTHON) candidates.push({ command: process.env.BOB_PYTHON, prefix: [] });
  if (process.env.PYTHON) candidates.push({ command: process.env.PYTHON, prefix: [] });
  candidates.push({
    command: process.platform === "win32"
      ? path.join(root, ".venv", "Scripts", "python.exe")
      : path.join(root, ".venv", "bin", "python"),
    prefix: [],
  });
  candidates.push({ command: "python", prefix: [] });
  candidates.push({ command: "python3", prefix: [] });
  if (process.platform === "win32") candidates.push({ command: "py", prefix: ["-3"] });

  for (const candidate of candidates) {
    if (path.isAbsolute(candidate.command) && !fs.existsSync(candidate.command)) continue;
    const probe = spawnSync(candidate.command, [...candidate.prefix, "--version"], {
      encoding: "utf8",
      windowsHide: true,
    });
    if (probe.status === 0) return candidate;
  }
  throw new Error(
    "Python 3 was not found. Create .venv or set BOB_PYTHON to the Python executable.",
  );
}
