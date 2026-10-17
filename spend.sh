#!/bin/zsh
# Show OpenRouter spend. Makes no model calls (reads /key, /credits, /models and agent.log only).
# Usage: ./spend.sh
cd "$(dirname "$0")" || exit 1

docker exec hermes sh -c 'cd /opt/data && set -a && . ./.env 2>/dev/null; set +a; python3 - <<EOF
import json, os, re, urllib.request

key = os.environ["OPENROUTER_API_KEY"]

def get(path):
    req = urllib.request.Request("https://openrouter.ai/api/v1" + path, headers={"Authorization": "Bearer " + key})
    return json.load(urllib.request.urlopen(req, timeout=20))["data"]

credits, info = get("/credits"), get("/key")
print("Credits bought: \$%.2f | used: \$%.4f | left: \$%.4f" % (credits["total_credits"], credits["total_usage"], credits["total_credits"] - credits["total_usage"]))
print("Key limit: %s | key usage: \$%.4f" % (info.get("limit"), info.get("usage", 0)))

price = {m["id"]: m["pricing"] for m in get("/models")}
calls = {}
pattern = re.compile(r"API call #\d+: model=(\S+) provider=openrouter .*? in=(\d+) out=(\d+)")
for line in open("/opt/data/logs/agent.log", errors="ignore"):
    m = pattern.search(line)
    if m and not m.group(1).endswith(":free"):
        model, tin, tout = m.group(1), int(m.group(2)), int(m.group(3))
        c = calls.setdefault(model, [0, 0, 0])
        c[0] += 1; c[1] += tin; c[2] += tout

if not calls:
    print("Paid-model calls in agent.log: none")
for model, (n, tin, tout) in calls.items():
    p = price.get(model)
    cost = (tin * float(p["prompt"]) + tout * float(p["completion"])) if p else float("nan")
    print("%s: %d calls, %d tokens in, %d out, ~\$%.4f (estimate, no cache discount)" % (model, n, tin, tout, cost))
EOF'
