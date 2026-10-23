#!/usr/bin/env bash
# Runs ON THE SERVER. One command to apply what was pushed from the Mac:  ./ops/update.sh
# Re-runs itself as root (data/ belongs to the container user and only root can read it), pulls, fixes ownership,
# restarts only when needed, then runs check.sh and prints just the problems.
set -euo pipefail
[ "$(id -u)" -eq 0 ] || exec sudo "$0" "$@"
cd "$(dirname "$0")/.."
REPO=$(pwd)
OWNER=$(stat -c %U "$REPO")
git config --global --get-all safe.directory | grep -qx "$REPO" || git config --global --add safe.directory "$REPO"

# Hermes rewrites a few keys of config.yaml by itself (e.g. onboarding flags). Keep a copy of that drift, then drop it.
drift=$(git status --porcelain --untracked-files=no)
if [ -n "$drift" ]; then
  other=$(printf '%s\n' "$drift" | grep -v ' data/config.yaml$' || true)
  if [ -n "$other" ]; then echo "Unexpected local changes on the server, not touching anything:"; echo "$other"; exit 2; fi
  mkdir -p data/backups
  patch="data/backups/config-drift-$(date +%Y%m%d-%H%M%S).patch"
  git diff data/config.yaml > "$patch"
  echo "Hermes edited config.yaml itself (saved in $patch):"
  grep -E '^[+-][^+-]' "$patch" | sed 's/^/  /' || true
  git checkout -- data/config.yaml
fi

before=$(git rev-parse HEAD)
git pull --ff-only
after=$(git rev-parse HEAD)
chown -R "$OWNER:$OWNER" .git
chown -R 10000:10000 data
if [ "$before" = "$after" ]; then echo "Already up to date."; else
  changed=$(git diff --name-only "$before" "$after")
  echo "Changed files:"; echo "$changed" | sed 's/^/  /'
  if echo "$changed" | grep -q '^docker-compose.yml$'; then
    if docker compose version >/dev/null 2>&1; then docker compose up -d; else echo "docker-compose.yml changed: recreate the container by hand."; fi
    sleep 20
  elif echo "$changed" | grep -qE '^data/(config.yaml|SOUL.md|skills/)'; then
    docker restart hermes >/dev/null && echo "Restarted hermes (config, persona or skills changed)."
    sleep 20
  else
    echo "No restart needed (scripts are read on each run)."
  fi
  echo "$changed" | grep -q '^ops/bootstrap-audio.sh$' && echo "NOTE: bootstrap-audio.sh changed; run it if audio breaks."
fi

echo; echo "== check =="
out=$(./check.sh 2>&1 || true)
echo "$out" | grep -E '✗|⚠|Result' || echo "$out" | tail -5
