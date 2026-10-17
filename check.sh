#!/bin/bash
# Hermes health and regression check. Makes NO model calls (config, files, MCP handshake, OpenRouter /key and /credits only).
# Usage: ./check.sh        Exit code = number of failed checks.
cd "$(dirname "$0")" || exit 1
FAIL=0; WARN=0
ok()   { echo "  ✓ $*"; }
warn() { echo "  ⚠ $*"; WARN=$((WARN+1)); }
bad()  { echo "  ✗ $*"; FAIL=$((FAIL+1)); }

echo "== Container =="
if docker ps --format '{{.Names}}' | grep -qx hermes; then
  ok "running: $(docker ps --filter name=^hermes$ --format '{{.Status}}')"
else bad "container not running"; exit 1; fi
[ "$(docker inspect hermes --format '{{.State.OOMKilled}}')" = "false" ] && ok "not OOM-killed" || bad "OOM-killed"
docker logs --since 24h hermes 2>&1 | grep -q "Connected to Telegram" && ok "Telegram connected (last 24h)" || warn "no Telegram connect seen in 24h logs"

echo "== Config, tools, prompt weight (in container) =="
INCONT=$(docker exec -i -u hermes -e HERMES_HOME=/opt/data -w /opt/hermes hermes /opt/hermes/.venv/bin/python - < "$(dirname "$0")/check_inner.py" 2>&1 | grep -v "no valid toolsets")
echo "$INCONT"
FAIL=$((FAIL + $(echo "$INCONT" | grep -c '✗')))
WARN=$((WARN + $(echo "$INCONT" | grep -c '⚠')))
echo "$INCONT" | grep -q 'Traceback' && bad "in-container checks crashed"

echo "== MCP =="
OUT=$(docker exec -u hermes -e HERMES_HOME=/opt/data hermes hermes mcp test maybe 2>&1)
echo "$OUT" | grep -q "Connected" && ok "MCP 'maybe' connected: $(echo "$OUT" | grep -o 'Tools discovered: [0-9]*')" || bad "MCP 'maybe' not reachable (is the app running on :3000?)"

echo "== Spend =="
./spend.sh 2>&1 | sed 's/^/  /'
LIM=$(./spend.sh 2>/dev/null | grep -o 'Key limit: [0-9.]*' | grep -o '[0-9.]*$')
BOUGHT=$(./spend.sh 2>/dev/null | grep -o "bought: \$[0-9.]*" | grep -o "[0-9.]*$")
[ -n "$BOUGHT" ] && awk "BEGIN{exit !($BOUGHT > 10)}" && warn "credits bought \$$BOUGHT: the key limit (\$$LIM) is not the cap, consider lowering it"

echo "== Operations =="
NEWEST=$(ls -t ~/hermes-docker-backups 2>/dev/null | head -1)
[ -n "$NEWEST" ] && ok "latest manual backup: $NEWEST" || warn "no backups"
AGE=$(find ~/hermes-docker-backups -maxdepth 1 -mtime -2 2>/dev/null | wc -l)
[ "$AGE" -gt 1 ] && ok "a backup exists from the last 2 days" || warn "no backup in the last 2 days (no automated backup yet)"
DIRTY=$(git -C vault status --short 2>/dev/null | wc -l | tr -d ' ')
[ "$DIRTY" = "0" ] && ok "notes git tree clean" || ok "notes git tree has $DIRTY uncommitted change(s) (no automatic commits; backups not required by the user)"

echo
echo "Result: $FAIL failed, $WARN warnings"
exit $FAIL
