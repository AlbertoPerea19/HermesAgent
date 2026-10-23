#!/usr/bin/env bash
# Runs ON THE SERVER. Preview the politics briefing while polishing it.
#   ./ops/briefing.sh                      print it here (does NOT send to Telegram; one cheap model call)
#   BRIEFING_MODEL=deepseek/deepseek-v4-flash ./ops/briefing.sh   try another model
#   ./ops/briefing.sh send                 run the real cron job now (delivers to Telegram)
set -euo pipefail
[ "$(id -u)" -eq 0 ] || exec sudo -E "$0" "$@"
C=${HERMES_CONTAINER:-hermes}
if [ "${1:-}" = send ]; then
  docker exec -u hermes -e HERMES_HOME=/opt/data "$C" hermes cron run 8ba9c7852e94
  exit
fi
args=(-e HERMES_HOME=/opt/data -e BRIEFING_DEBUG=1 -e BRIEFING_INBOX=/tmp/briefing-preview)
[ -n "${BRIEFING_MODEL:-}" ] && args+=(-e "BRIEFING_MODEL=$BRIEFING_MODEL")
docker exec -u hermes "${args[@]}" "$C" python3 /opt/data/scripts/news_briefing.py
