import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import test from "node:test";
import { DevStore } from "../dev-store.js";

test("DLQ corrections create linked evaluations and redact secrets", () => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), "bob-dev-")); const store = new DevStore({ dataRoot: root }); const admin = { id: "admin-1" };
  try {
    const dlq = store.createDlq({ prompt: "fix login token=secret-value", error: { message: "Authorization: Bearer abc.def.ghi" } });
    assert.doesNotMatch(dlq.prompt, /secret-value/); store.claimDlq(dlq.id, admin, "prompt");
    const result = store.correctDlq(dlq.id, admin, { corrected_prompt: "Fix login safely", expected_behavior: "No credential leakage", notes: "Validate auth boundaries", severity: "high", tags: ["auth"] });
    assert.equal(result.correction.source_id, dlq.id); assert.equal(result.evaluation.status, "pending");
    assert.equal(store.list("dlq").dlq[0].status, "resolved_evaluation_created");
    store.recordFeedback({ action: "force-applied", workspace_id: "demo", authorization: "Bearer do-not-store" });
    store.recordUsage({ usage: { input_tokens: 12, output_tokens: 4 }, estimated_cost_usd: 0.01 });
    assert.equal(store.list("feedback").feedback[0].authorization, undefined);
    assert.equal(store.overview().input_tokens, 12);
  } finally { fs.rmSync(root, { recursive: true, force: true }); }
});

test("runtime JSONL logs redact even short configured secrets", () => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), "bob-dev-log-"));
  const previous = process.env.BOB_COLAB_TOKEN; process.env.BOB_COLAB_TOKEN = "tiny";
  try {
    const store = new DevStore({ dataRoot: root });
    store.appendLog("model.test", { message: "token=tiny Bearer abc.def.ghi", authorization: "Bearer hidden", code: "do not store" });
    const [record] = store.logs(); const encoded = JSON.stringify(record);
    assert.doesNotMatch(encoded, /tiny|abc\.def\.ghi|do not store/);
    assert.equal(record.authorization, undefined); assert.equal(record.code, undefined);
  } finally {
    if (previous === undefined) delete process.env.BOB_COLAB_TOKEN; else process.env.BOB_COLAB_TOKEN = previous;
    fs.rmSync(root, { recursive: true, force: true });
  }
});

test("developer logs correlate app, model, and ngrok records", () => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), "bob-dev-sources-"));
  try {
    const store = new DevStore({ dataRoot: root });
    store.appendLog("http.request", { request_id: "req-1", trace_id: "trace-1", run_id: "run-1" });
    fs.writeFileSync(path.join(root, "runtime", "model-events.jsonl"), `${JSON.stringify({ timestamp: "2026-08-07T10:00:01.000Z", event: "model.stage", request_id: "req-1", trace_id: "trace-1", run_id: "run-1" })}\n`);
    fs.writeFileSync(path.join(root, "runtime", "ngrok-events.jsonl"), `${JSON.stringify({ timestamp: "2026-08-07T10:00:02.000Z", event: "tunnel.response", request_id: "req-1", trace_id: "trace-1", run_id: "run-1" })}\n`);
    const records = store.logs({ source: "all", trace_id: "trace-1" });
    assert.deepEqual(new Set(records.map((record) => record.source)), new Set(["app", "model", "ngrok"]));
    assert.equal(store.logs({ source: "model", event: "model.stage", run_id: "run-1" }).length, 1);
    assert.equal(store.logs({ source: "ngrok", request_id: "different" }).length, 0);
  } finally { fs.rmSync(root, { recursive: true, force: true }); }
});
