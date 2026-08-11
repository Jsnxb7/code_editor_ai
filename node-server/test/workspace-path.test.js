import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import test from "node:test";
import { safeWorkspacePath } from "../workspace-path.js";

test("workspace paths stay inside the selected project", () => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), "bob-path-"));
  const projectRef = "worker--00000000-0000-0000-0000-000000000001/sample_project";
  fs.mkdirSync(path.join(root, ...projectRef.split("/")), { recursive: true });
  try {
    const target = safeWorkspacePath(root, projectRef, "app.py");
    assert.equal(target, path.join(root, ...projectRef.split("/"), "app.py"));
    assert.throws(() => safeWorkspacePath(root, projectRef, "../../admin--00000000-0000-0000-0000-000000000002/secret/app.py"), /escapes selected workspace/);
  } finally { fs.rmSync(root, { recursive: true, force: true }); }
});

test("workspace project traversal is rejected", () => {
  assert.throws(() => safeWorkspacePath(path.resolve("workspace"), ".."), /Invalid workspace/);
});
