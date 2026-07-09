import assert from "node:assert/strict";
import path from "node:path";
import test from "node:test";
import { readConfig } from "../config.js";
import { safeWorkspacePath } from "../workspace-path.js";

test("workspace paths stay inside the selected project", () => {
  const config = readConfig();
  const target = safeWorkspacePath(config.workspaceRoot, "sample_project", "app.py");
  assert.equal(target, path.join(config.workspaceRoot, "sample_project", "app.py"));
  assert.throws(
    () => safeWorkspacePath(config.workspaceRoot, "sample_project", "../Hello/app.py"),
    /escapes selected workspace/,
  );
});

test("workspace project traversal is rejected", () => {
  const config = readConfig();
  assert.throws(() => safeWorkspacePath(config.workspaceRoot, ".."), /Invalid workspace/);
});
