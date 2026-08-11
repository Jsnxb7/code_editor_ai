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
  const realRoot = fs.realpathSync(root);
  const realProject = fs.realpathSync(projectRoot);
  if (realProject === realRoot || !realProject.startsWith(`${realRoot}${path.sep}`)) throw new Error("Workspace project escapes storage root");
  let existing = target;
  while (!fs.existsSync(existing) && existing !== projectRoot) existing = path.dirname(existing);
  const realExisting = fs.realpathSync(existing);
  if (realExisting !== realProject && !realExisting.startsWith(`${realProject}${path.sep}`)) throw new Error("Path escapes selected workspace project through a link");
  return target;
}
