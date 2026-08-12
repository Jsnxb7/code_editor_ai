#!/usr/bin/env bash
set -euo pipefail

source /home/ubuntu/bob-admin-credentials.txt
exec sudo -u bob env \
  BOB_URL="http://127.0.0.1:3000" \
  BOB_SMOKE_USERNAME="$username" \
  BOB_SMOKE_PASSWORD="$password" \
  /usr/bin/node /opt/bob-ide/scripts/live-auth-smoke.mjs
