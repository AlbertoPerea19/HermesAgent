#!/bin/bash
# Runs ON THE MAC: pushes committed changes to GitHub and applies them on the server over SSH.
# Usage: ./deploy.sh [ssh-host-alias]   (default alias: hermes-vps)
set -euo pipefail
HOST=${1:-hermes-vps}
cd "$(dirname "$0")"
if [ -n "$(git status --porcelain)" ]; then echo "Commit your changes first:"; git status --short; exit 2; fi
git push
ssh "$HOST" 'cd ~/hermes && ./ops/apply.sh'
