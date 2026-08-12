#!/usr/bin/env bash
set -euo pipefail

app_root="${BOB_APP_ROOT:-/opt/bob-ide}"
users_file="$app_root/data/auth/users.json"
owners_file="$app_root/data/auth/workspace-owners.json"

readarray -t identity < <(/usr/bin/node -e '
  const data = JSON.parse(require("fs").readFileSync(process.argv[1], "utf8"));
  if (data.users.length !== 1) throw new Error("Expected exactly one initial administrator");
  console.log(data.users[0].id);
  console.log(data.users[0].username);
' "$users_file")
user_id="${identity[0]}"
username="${identity[1]}"
scope="${username}--${user_id}"
user_root="$app_root/workspace/$scope"

[[ -d "$user_root" ]] || { echo "Missing user root: $user_root" >&2; exit 1; }

sudo systemctl stop bob-app.service bob-mcp.service
restart_services() {
  sudo systemctl start bob-mcp.service bob-app.service
}
trap restart_services EXIT

shopt -s nullglob
for legacy_root in "$user_root"/*--*; do
  [[ -d "$legacy_root" ]] || continue
  for project in "$legacy_root"/*; do
    [[ -d "$project" ]] || continue
    target="$user_root/$(basename "$project")"
    [[ ! -e "$target" ]] || { echo "Refusing to overwrite existing project: $target" >&2; exit 1; }
    mv -- "$project" "$target"
  done
  rmdir -- "$legacy_root"
done

/usr/bin/node -e '
  const fs = require("fs");
  const path = require("path");
  const [ownersFile, userRoot, scope, userId] = process.argv.slice(1);
  const current = JSON.parse(fs.readFileSync(ownersFile, "utf8"));
  const owners = Object.fromEntries(Object.entries(current.owners || {}).filter(([, owner]) => owner !== userId));
  for (const entry of fs.readdirSync(userRoot, { withFileTypes: true })) {
    if (entry.isDirectory() && entry.name !== ".bob") owners[`${scope}/${entry.name}`] = userId;
  }
  const temporary = `${ownersFile}.tmp`;
  fs.writeFileSync(temporary, `${JSON.stringify({ schema_version: "2.0", owners }, null, 2)}\n`, { mode: 0o600 });
  fs.renameSync(temporary, ownersFile);
' "$owners_file" "$user_root" "$scope" "$user_id"

chown -R bob:bob "$user_root" "$owners_file"
echo "workspace_normalized=$scope"
find "$user_root" -maxdepth 2 -mindepth 1 -type d -printf '%P\n' | sort
