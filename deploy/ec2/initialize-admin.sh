#!/usr/bin/env bash
set -euo pipefail

base_url="${BOB_LOCAL_URL:-http://127.0.0.1:3000}"
public_url="${BOB_PUBLIC_URL:-http://ec2-16-192-154-27.eu-north-1.compute.amazonaws.com}"
credentials_file="${BOB_CREDENTIALS_FILE:-/home/ubuntu/bob-admin-credentials.txt}"
username="${BOB_INITIAL_ADMIN_USERNAME:-shourya}"
display_name="${BOB_INITIAL_ADMIN_DISPLAY_NAME:-Shourya}"

status_payload="$(curl --fail --silent --show-error "$base_url/api/auth/status")"
if [[ "$status_payload" == *'"setup_required":true'* ]]; then
  password="$(openssl rand -hex 16)"
  payload="$(printf '{"username":"%s","display_name":"%s","password":"%s"}' "$username" "$display_name" "$password")"
  status="$(curl --silent --show-error --output /tmp/bob-setup-response.json --write-out '%{http_code}' \
    --header 'Content-Type: application/json' --data "$payload" "$base_url/api/auth/setup")"
  if [[ "$status" != "201" ]]; then
    cat /tmp/bob-setup-response.json >&2
    exit 1
  fi
  umask 077
  printf 'URL=%s\nusername=%s\npassword=%s\n' "$public_url" "$username" "$password" > "$credentials_file"
  chmod 600 "$credentials_file"
  echo "admin_created=yes"
else
  echo "admin_created=already_configured"
fi

curl --fail --silent --show-error "$base_url/api/auth/status"
printf '\ncredentials_file='
stat -c '%n mode=%a owner=%U' "$credentials_file"
