#!/bin/bash
# Runs ON THE SERVER inside the repo checkout. Pulls the latest tracked files and applies them safely.
set -euo pipefail
cd "$(dirname "$0")/.."

if [ -n "$(git status --porcelain)" ]; then
  echo "Local changes on the server (drift). Review before deploying:"; git status --short; exit 2
fi
before=$(git rev-parse HEAD)
git pull --ff-only
after=$(git rev-parse HEAD)
[ "$before" = "$after" ] && { echo "Already up to date."; exit 0; }

changed=$(git diff --name-only "$before" "$after")
echo "Changed files:"; echo "$changed" | sed 's/^/  /'
if echo "$changed" | grep -q '^docker-compose.yml$'; then
  docker compose up -d                       # recreates the container if the definition changed
elif echo "$changed" | grep -q -E '^data/(config.yaml|SOUL.md|skills/|scripts/)'; then
  docker compose restart hermes              # config and SOUL.md are read at start; sessions cache the system prompt
fi
./check.sh
