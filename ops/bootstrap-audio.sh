#!/usr/bin/env bash
# One-time (per fresh install) audio setup for the English tutor: installs Piper (text-to-speech) and its voice into the
# hermes-installs volume. Safe to re-run. The voice file downloads on first use (needs internet); restart the container afterwards. Needs the container running and internet access. Run on the server as: sudo ./ops/bootstrap-audio.sh
set -euo pipefail
C=${1:-hermes}
# a fresh named volume is created owned by root; the agent user must be able to write to it
docker exec -u root "$C" chown -R 10000:10000 /opt/data/installs
docker exec -u hermes -e HERMES_HOME=/opt/data "$C" hermes tools post-setup piper
# Edge TTS (natural neural voices). Both extras are named so installing one never drops the other.
docker exec -u hermes -e HERMES_HOME=/opt/data "$C" hermes pm install --extra piper --extra edge-tts
docker exec -i -u hermes -e HERMES_HOME=/opt/data "$C" python3 - <<'PY'
import glob, sys
for sp in glob.glob("/opt/data/installs/**/venv/lib/python3.14/site-packages", recursive=True):
    sys.path.insert(0, sp)
import edge_tts, piper
print("piper and edge-tts import ok")
PY
