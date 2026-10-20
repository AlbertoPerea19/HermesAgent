# Run inside the container by check.sh (no model calls).
import json, os
from ruamel.yaml import YAML
from pathlib import Path
home = Path("/opt/data")
cfg = YAML(typ="safe").load((home / "config.yaml").read_text())
def ok(m): print("  ✓ " + m)
def warn(m): print("  ⚠ " + m)
def bad(m): print("  ✗ " + m)

pt = cfg.get("platform_toolsets", {})
tg = set(pt.get("telegram", []))
for risky in ("terminal", "browser", "code_execution"):
    (bad if risky in tg else ok)(f"telegram without {risky}" if risky not in tg else f"telegram HAS {risky}")
ok("telegram has cronjob (needs confirm-before-create rule in SOUL.md)" if "cronjob" in tg else "telegram without cronjob (no reminders by chat)")
ok(f"telegram delegation = {'delegation' in tg}; children model = {cfg.get('delegation', {}).get('model')}, max children {cfg.get('delegation', {}).get('max_concurrent_children')}, iterations {cfg.get('delegation', {}).get('max_iterations')}")
fb = cfg.get("fallback_providers", [])
(ok if len(fb) >= 1 else warn)(f"primary: {cfg['model']['default']} | fallback chain: {[f['model'] for f in fb]}")
t = cfg.get("providers", {}).get("openrouter", {}).get("request_timeout_seconds")
(ok if t and t <= 120 else bad)(f"openrouter request timeout = {t}s (default 1800s hangs cron)")
aux = cfg.get("auxiliary", {})
(ok if aux.get("title_generation", {}).get("enabled") is False else warn)("title_generation disabled (it burns free requests)")
(ok if aux.get("background_review", {}).get("enabled") is False else warn)("background_review disabled")
(ok if cfg.get("agent", {}).get("reasoning_effort") in ("low", "minimal") else warn)(f"reasoning_effort = {cfg.get('agent', {}).get('reasoning_effort')}")
(ok if cfg.get("stt", {}).get("language", "x") == "" else warn)("stt language auto-detect")

from agent.file_safety import get_read_block_error as g
(ok if not g("/opt/data/notes/Tutor/Profile.md") else bad)("notes readable by read_file")
(ok if g("/opt/data/.env") else bad)(".env protected from read_file")
nm = Path("/opt/data/notes")
(ok if nm.is_dir() and any(nm.iterdir()) else bad)("/opt/data/notes mounted and non-empty")
(ok if not Path("/opt/data/vault").exists() else bad)("no /opt/data/vault directory (reserved by Hermes)")

from model_tools import get_tool_definitions as gtd
def toks(ts):
    d = gtd(enabled_toolsets=ts, quiet_mode=True)
    return len(d), sum(len(json.dumps(x)) for x in d) // 4
for label, ts, limit in (("telegram", sorted(tg - {"browser", "terminal", "code_execution"}), 7000), ("cron lesson", ["file", "skills"], 3500), ("cron briefing", ["file"], 2000)):
    n, k = toks(ts)
    (ok if k <= limit else warn)(f"tool schemas {label}: {n} tools ~{k} tokens (limit {limit})")
from agent import prompt_builder as pb
sk = pb.build_skills_system_prompt(available_tools={"skill_view", "skills_list", "read_file", "write_file"}, available_toolsets={"file", "skills", "memory", "clarify", "web"}) or ""
(ok if len(sk) // 4 <= 800 else warn)(f"skills index ~{len(sk)//4} tokens")
soul = pb.load_soul_md() or ""
(ok if len(soul) // 4 <= 1600 else warn)(f"SOUL.md ~{len(soul)//4} tokens")
for f in ("MEMORY.md", "USER.md"):
    p = home / "memories" / f
    (ok if p.exists() and p.stat().st_size > 0 else warn)(f"memories/{f}: {p.stat().st_size if p.exists() else 0} bytes")

jobs = json.load(open(home / "cron" / "jobs.json"))["jobs"]
for j in jobs:
    st = f"streak={j.get('failure_streak')} last={j.get('last_status')}"
    (ok if not j.get("failure_streak") else bad)(f"cron '{j['name']}': {st}, toolsets={j.get('enabled_toolsets')}, next={j.get('next_run_at')}")
    (ok if j.get("enabled_toolsets") else warn)(f"cron '{j['name']}' has a toolset whitelist")

for j in jobs:
    if j.get("no_agent"):
        ok(f"cron '{j['name']}' runs without a model (script only, 0 tokens)")

# ---- voice (tutor listening/speaking) ----
import re
stt = cfg.get("stt", {})
prov = stt.get("provider")
(ok if prov == "groq" else warn)(f"stt provider = {prov}" + (" (needs GROQ_API_KEY)" if prov == "groq" else ""))
if prov == "groq":
    envtxt = (home / ".env").read_text(errors="ignore") if (home / ".env").exists() else ""
    has_key = bool(os.environ.get("GROQ_API_KEY")) or bool(re.search(r"^GROQ_API_KEY=.+", envtxt, re.M))
    (ok if has_key else bad)("GROQ_API_KEY set in data/.env")
import subprocess
try:
    # same activation as the gateway (a bare python process does not see the installs volume)
    out = subprocess.run(["hermes", "doctor"], capture_output=True, text=True, timeout=90).stdout
    tts_ok = any("tts" in l.lower() and "\u2713" in l for l in out.splitlines())
    (ok if tts_ok else bad)(f"text-to-speech available (provider {cfg.get('tts', {}).get('provider')}); if not, run ops/bootstrap-audio.sh")
except Exception as e:
    warn(f"could not run hermes doctor: {e}")
log = home / "logs" / "agent.log"
if log.exists():
    today = __import__("datetime").date.today().isoformat()
    secs = n = 0.0
    for line in log.read_text(errors="ignore").splitlines()[-20000:]:
        if line.startswith(today) and "Transcribed " in line:
            n += 1
            m = re.search(r"([\d.]+)s audio", line)
            secs += float(m.group(1)) if m else 0
    (ok if secs <= 3600 else warn)(f"voice notes transcribed today: {int(n)} ({secs/60:.1f} min of audio; Groq free tier ~480 min/day)")
