import fs from "node:fs";
import path from "node:path";

export function safeWorkspacePath(workspaceRoot, project, relativePath = "") {
  if (!project || project === "." || project === ".." || path.isAbsolute(project)) {
    throw new Error("Invalid workspace project");
  }
  const root = path.resolve(workspaceRoot);
  const projectRoot = path.resolve(root, project);
  if (projectRoot === root || !projectRoot.startsWith(`${root}${path.sep}`)) {
    throw new Error("Invalid workspace project");
  }
  const target = path.resolve(projectRoot, relativePath);
  if (target !== projectRoot && !target.startsWith(`${projectRoot}${path.sep}`)) {
    throw new Error("Path escapes selected workspace project");
  }
  if (!fs.existsSync(projectRoot) || !fs.statSync(projectRoot).isDirectory()) {
    throw new Error("Workspace project not found");
  }
  return target;
}
