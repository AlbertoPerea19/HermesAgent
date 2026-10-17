#!/usr/bin/env python3
"""Daily English lesson reminder. Zero model tokens: reads the weekly rotation from the notes and prints one message.

Run as a no-agent cron job: stdout is delivered to Telegram as is.
The lesson itself starts only when the user replies, so a model is used on demand, never on a schedule.
"""
import re
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

NOTES = Path("/opt/data/notes/Tutor")
DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


def todays_focus(plan_text: str, day: str) -> str:
    match = re.search(rf"^\|\s*{day}\s*\|\s*(.+?)\s*\|\s*$", plan_text, re.M)
    if not match:
        return "Mixed review"
    return re.sub(r"\[\[(.+?)\]\]", r"\1", match.group(1))


def main() -> None:
    now = datetime.now(ZoneInfo("America/Mexico_City"))
    day = DAYS[now.weekday()]
    try:
        plan = (NOTES / "Plan.md").read_text(encoding="utf-8")
    except OSError:
        plan = ""
    try:
        profile = (NOTES / "Profile.md").read_text(encoding="utf-8")
    except OSError:
        profile = ""

    lines = [f"Good morning! English session time (20-30 min). Today's focus: {todays_focus(plan, day)}."]
    if re.search(r"Estimated level:\*\*\s*pending", profile, re.I):
        lines.append("Your level is still pending, so we would start with the placement test.")
    lines.append('Reply "English lesson" whenever you want to start. If today is not the day, just ignore this.')
    print("\n".join(lines))


if __name__ == "__main__":
    main()
