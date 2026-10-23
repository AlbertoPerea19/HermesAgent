#!/usr/bin/env bash
# Runs ON THE MAC. Commits everything tracked and pushes it.  Usage: ./deploy.sh "what changed"
set -euo pipefail
cd "$(dirname "$0")"
git add -A
if git diff --cached --quiet; then echo "Nothing new to commit."; else git commit -qm "${1:?give a commit message}"; fi
git push
echo
echo "Now, on the server (as any user with sudo):  cd ~/HermesAgent && ./ops/update.sh"
