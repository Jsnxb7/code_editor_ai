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
