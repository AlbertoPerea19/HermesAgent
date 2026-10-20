#!/usr/bin/env bash
# One-time (per fresh install) audio setup for the English tutor: installs Piper (text-to-speech) and its voice into the
# hermes-installs volume. Safe to re-run. The voice file downloads on first use (needs internet); restart the container afterwards. Needs the container running and internet access. Run on the server as: sudo ./ops/bootstrap-audio.sh
set -euo pipefail
C=${1:-hermes}
docker exec -u hermes -e HERMES_HOME=/opt/data "$C" hermes tools post-setup piper
docker exec -u hermes -e HERMES_HOME=/opt/data "$C" python3 - <<'PY'
import glob, sys
for sp in glob.glob("/opt/data/installs/**/venv/lib/python3.14/site-packages", recursive=True):
    sys.path.insert(0, sp)
import piper
print("piper import ok")
PY
