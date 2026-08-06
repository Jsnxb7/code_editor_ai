import fs from "node:fs";
import path from "node:path";
import { spawnSync } from "node:child_process";
import { fileURLToPath } from "node:url";
import { findPython } from "./python-command.mjs";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const filename = "Untitled28_lightning_ai_bob_runtime.ipynb";
const notebookPath = path.join(root, filename);
const notebook = JSON.parse(fs.readFileSync(notebookPath, "utf8"));
const text = fs.readFileSync(notebookPath, "utf8");
const finalContract = (notebook.cells[29]?.source || []).join("");

const failures = [];
if (notebook.nbformat !== 4) failures.push("Notebook must use nbformat 4");
if (notebook.metadata?.bob_runtime_contract !== "bob-colab-v4-llmops") failures.push("Missing v4 runtime metadata");
if (notebook.cells.some((cell) => (cell.outputs || []).length)) failures.push("Notebook contains stale execution outputs");
for (const pattern of [/hf_[A-Za-z0-9]{12,}/, /github_pat_[A-Za-z0-9_]{12,}/, /nontyrannous-congratulatorily-maribel/]) {
  if (pattern.test(text)) failures.push(`Potential embedded secret or stale tunnel URL: ${pattern}`);
}
for (const required of ["BOB_COLAB_TOKEN is not configured", "hmac.compare_digest", "_bob_request_lock", "usage_reporting", "request_tracing", "_structured_error", "MAX_CONTENT_LENGTH"]) {
  if (!finalContract.includes(required)) failures.push(`Final runtime is missing: ${required}`);
}
if (finalContract.includes("CORS(app)")) failures.push("Final runtime must not enable browser-wide CORS");
if (/jsonify\([^\n]*traceback/.test(finalContract)) failures.push("Final runtime exposes a traceback over HTTP");

const python = findPython(root);
const syntaxCheck = [
  "import ast,json,pathlib,sys",
  `n=json.loads(pathlib.Path(${JSON.stringify(notebookPath)}).read_text(encoding='utf-8'))`,
  "errors=[]",
  "for i,c in enumerate(n['cells']):",
  "    if c.get('cell_type') == 'code':",
  "        source=''.join(c.get('source', []))",
  "        source='\\n'.join(('# '+line if line.lstrip().startswith(('%','!')) else line) for line in source.splitlines())",
  "        try: ast.parse(source, filename=f'cell-{i}')",
  "        except SyntaxError as exc: errors.append(f'cell {i}: {exc.msg} line {exc.lineno}')",
  "print('\\n'.join(errors))",
  "sys.exit(1 if errors else 0)",
].join("\n");
const result = spawnSync(python.command, [...python.prefix, "-c", syntaxCheck], { cwd: root, encoding: "utf8", windowsHide: true });
if (result.status !== 0) failures.push(result.stdout.trim() || result.stderr.trim() || "Python cell syntax validation failed");

if (failures.length) {
  console.error(failures.map((item) => `- ${item}`).join("\n"));
  process.exit(1);
}
console.log(`Notebook verified: ${notebook.cells.length} cells, zero outputs, v4 LLMOps contract, Python syntax valid.`);
