import path from "node:path";
import { spawn } from "node:child_process";
import { fileURLToPath } from "node:url";
import { findPython } from "./python-command.mjs";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
let python;
try {
  python = findPython(root);
} catch (error) {
  console.error(error.message);
  process.exit(1);
}
const child = spawn(python.command, [...python.prefix, ...process.argv.slice(2)], {
  cwd: root,
  env: process.env,
  stdio: "inherit",
  windowsHide: true,
});

child.on("error", (error) => {
  console.error(error.message);
  process.exitCode = 1;
});
child.on("exit", (code, signal) => {
  if (signal) process.kill(process.pid, signal);
  else process.exit(code ?? 1);
});

for (const signal of ["SIGINT", "SIGTERM"]) {
  process.on(signal, () => {
    if (!child.killed) child.kill(signal);
  });
}
