import fs from "node:fs";
import path from "node:path";
import { spawnSync } from "node:child_process";
import { fileURLToPath } from "node:url";
import { findPython } from "./python-command.mjs";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const candidates = [process.env.BOB_RUNTIME_NOTEBOOK, "Untitled28_lightning_ai_bob_runtime (1).ipynb", "Untitled28_lightning_ai_bob_runtime.ipynb"].filter(Boolean);
const filename = candidates.find((item) => fs.existsSync(path.join(root, item)));
if (!filename) throw new Error(`Runtime notebook not found; checked: ${candidates.join(", ")}`);
const notebookPath = path.join(root, filename);
const notebook = JSON.parse(fs.readFileSync(notebookPath, "utf8"));
const text = fs.readFileSync(notebookPath, "utf8");
const finalContractCells = notebook.cells.filter((cell) => {
  const source = (cell.source || []).join("");
  return source.includes('BOB_COLAB_CONTRACT_VERSION = "bob-colab-v4-llmops"') && source.includes('@app.post("/replan")');
});
const finalContract = (finalContractCells[0]?.source || []).join("");
const allCode = notebook.cells.filter((cell) => cell.cell_type === "code").map((cell) => (cell.source || []).join("")).join("\n");

const failures = [];
if (notebook.nbformat !== 4) failures.push("Notebook must use nbformat 4");
if (finalContractCells.length !== 1) failures.push(`Expected one final staged contract cell, found ${finalContractCells.length}`);
if (notebook.metadata?.bob_runtime_contract !== "bob-colab-v4-llmops") failures.push("Missing v4 runtime metadata");
if (notebook.cells.some((cell) => (cell.outputs || []).length)) failures.push("Notebook contains stale execution outputs");
for (const pattern of [/hf_[A-Za-z0-9]{12,}/, /github_pat_[A-Za-z0-9_]{12,}/, /nontyrannous-congratulatorily-maribel/]) {
  if (pattern.test(text)) failures.push(`Potential embedded secret or stale tunnel URL: ${pattern}`);
}
for (const required of ["BOB_COLAB_TOKEN is not configured", "hmac.compare_digest", "_bob_request_lock", "usage_reporting", "request_tracing", "structured_logging", "BOB_RUNTIME_LOG_DIR", "_bob_runtime_log", "evaluation_run_id", "test_id", "prompt_category", "approach", "pipeline_id", "model_lane", "BOB_MODEL_LANE_COUNT", "BOB_CONFIGURABLE_MODEL_LANES_V1_BEGIN", "_bob_pipeline_guard", "_structured_error", "MAX_CONTENT_LENGTH"]) {
  if (!finalContract.includes(required)) failures.push(`Final runtime is missing: ${required}`);
}
for (const required of ["_bob_request_context", "def _bob_context_files", "def preload_shared_model_lanes", "_bob_model_lanes", "unload(all_lanes=True)"]) {
  if (!text.includes(required)) failures.push(`Notebook concurrency helpers are missing: ${required}`);
}
if (finalContract.includes("CORS(app)")) failures.push("Final runtime must not enable browser-wide CORS");
if (/jsonify\([^\n]*traceback/.test(finalContract)) failures.push("Final runtime exposes a traceback over HTTP");
if (finalContract.includes("with _bob_request_lock:")) failures.push("Final runtime still serializes every request through the legacy global lock");
if ((finalContract.match(/_bob_pipeline_guard\(/g) || []).length < 8) failures.push("Every model endpoint must use a sticky pipeline lane guard");
if (/global\s+BOB_(PAYLOAD|CONTEXT_FILES|WORKSPACE_TREE|ACTIVE_PATH|PROJECT)/.test(text)) failures.push("Workspace context still uses process-global request state");
if (!allCode.includes('BOB_PRELOAD_MODEL_LANES", "1"')) failures.push("Notebook does not preload configured model lanes sequentially by default");
if (!allCode.includes("BOB_RUNTIME_MODE_SWITCH_V1")) failures.push("Notebook is missing the single/multi runtime mode switch");
if (!allCode.includes('BOB_NOTEBOOK_RUNTIME_MODE = "single"')) failures.push("Notebook must default safely to single-lane mode");
if (!allCode.includes('_requested_lane_count = 1 if _requested_runtime_mode == "single" else _requested_multi_lane_count')) failures.push("Lane count is not derived from the runtime mode");
if (!finalContract.includes('"runtime_mode": BOB_RUNTIME_MODE')) failures.push("Runtime health does not expose the selected mode");
if (notebook.metadata?.bob_concurrency?.runtime_mode_toggle !== true) failures.push("Notebook metadata does not advertise the runtime mode toggle");
if (notebook.metadata?.bob_concurrency?.model_lane_counts?.single !== 1 || notebook.metadata?.bob_concurrency?.model_lane_counts?.multi_max !== 3) failures.push("Notebook metadata has invalid single/multi lane counts");
if (notebook.metadata?.bob_concurrency?.thread_local_workspace_context !== true) failures.push("Notebook metadata does not confirm thread-local workspace context");
if (notebook.cells.filter((cell) => cell.cell_type === "code").some((cell) => !(cell.metadata?.tags || []).includes("bob-mode-both"))) failures.push("Every code cell must carry an explicit mode compatibility tag");

const python = findPython(root);
const syntaxCheck = [
  "import ast,json,os,pathlib,sys",
  "from typing import Any,Dict",
  `n=json.loads(pathlib.Path(${JSON.stringify(notebookPath)}).read_text(encoding='utf-8'))`,
  "errors=[]",
  "for i,c in enumerate(n['cells']):",
  "    if c.get('cell_type') == 'code':",
  "        source=''.join(c.get('source', []))",
  "        source='\\n'.join(('# '+line if line.lstrip().startswith(('%','!')) else line) for line in source.splitlines())",
  "        try: ast.parse(source, filename=f'cell-{i}')",
  "        except SyntaxError as exc: errors.append(f'cell {i}: {exc.msg} line {exc.lineno}')",
  "config=next((''.join(c.get('source', [])) for c in n['cells'] if 'BOB_RUNTIME_MODE_SWITCH_V1' in ''.join(c.get('source', []))), None)",
  "if config is None: errors.append('runtime mode configuration cell missing')",
  "else:",
  "    for mode,lanes in (('single',1),('multi',2)):",
  "        os.environ['BOB_RUNTIME_MODE']=mode",
  "        os.environ['BOB_MULTI_LANE_COUNT']='2'",
  "        namespace={'os':os,'Dict':Dict,'Any':Any,'print':lambda *args,**kwargs: None}",
  "        try: exec(config, namespace)",
  "        except Exception as exc: errors.append(f'{mode} mode configuration failed: {exc}')",
  "        else:",
  "            actual=(namespace.get('BOB_RUNTIME_MODE'), namespace.get('BOB_MODEL_LANE_COUNT'))",
  "            if actual != (mode,lanes): errors.append(f'{mode} mode resolved to {actual!r}')",
  "    os.environ.pop('BOB_RUNTIME_MODE',None)",
  "    os.environ.pop('BOB_MULTI_LANE_COUNT',None)",
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
