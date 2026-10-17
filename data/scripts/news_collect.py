"""Collect recent headlines from the configured feeds and print a compact Markdown digest.

Standard library only, no model calls. Output goes to the agent prompt (cron --script mode).
Always exits 0; failures are reported in the output so the agent can say so.
"""
import html, json, re, sys, urllib.request
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from zoneinfo import ZoneInfo

CFG = json.loads((Path(__file__).parent / "news_sources.json").read_text())
NOW = datetime.now(timezone.utc)
CUTOFF = NOW - timedelta(hours=CFG.get("window_hours", 30))
UA = {"User-Agent": "Mozilla/5.0 (compatible; HermesNewsBot/1.0)"}
NS = {"atom": "http://www.w3.org/2005/Atom", "rdf": "http://purl.org/rss/1.0/", "dc": "http://purl.org/dc/elements/1.1/"}


def parse_date(text):
    if not text:
        return None
    text = text.strip()
    try:
        d = parsedate_to_datetime(text)
    except Exception:
        try:
            d = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except Exception:
            return None
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def clean(text, limit):
    text = html.unescape(re.sub(r"<[^>]+>", " ", text or ""))
    text = re.sub(r"\s+", " ", text).strip()
    return text[:limit].rstrip() + ("..." if len(text) > limit else "")


def fetch(src):
    try:
        req = urllib.request.Request(src["url"], headers=UA)
        with urllib.request.urlopen(req, timeout=12) as r:
            root = ET.fromstring(r.read())
    except Exception as e:
        return src, [], f"{type(e).__name__}: {str(e)[:60]}"
    nodes = root.findall(".//item") or root.findall(".//rdf:item", NS) or root.findall(".//atom:entry", NS)
    out = []
    for n in nodes:
        def g(*tags):
            for t in tags:
                e = n.find(t, NS)
                if e is not None and (e.text or e.attrib.get("href")):
                    return (e.text or e.attrib.get("href") or "").strip()
            return ""
        title = clean(g("title", "rdf:title", "atom:title"), 160)
        link = g("link", "rdf:link", "atom:link")
        date = parse_date(g("pubDate", "dc:date", "atom:updated", "atom:published"))
        summary = clean(g("description", "rdf:description", "atom:summary", "content"), 140)
        if not title:
            continue
        if date and date < CUTOFF:
            continue
        out.append({"title": title, "link": link, "date": date, "summary": summary})
    out.sort(key=lambda x: x["date"] or datetime.min.replace(tzinfo=timezone.utc), reverse=True)
    return src, out[: src.get("max", 3)], None


def main():
    with ThreadPoolExecutor(max_workers=8) as ex:
        results = list(ex.map(fetch, CFG["sources"]))
    cap = CFG.get("max_items_total", 70)
    # round-robin so every outlet is represented before any outlet gets a second slot
    picked, rank = [], 0
    pools = [(s, items) for s, items, _ in results]
    while len(picked) < cap and any(rank < len(i) for _, i in pools):
        for s, items in pools:
            if rank < len(items) and len(picked) < cap:
                picked.append((s, items[rank]))
        rank += 1
    local = NOW.astimezone(ZoneInfo("America/Mexico_City"))
    print(f"# News collector output\nDate (America/Mexico_City): {local:%Y-%m-%d %H:%M}\n"
          f"Window: last {CFG.get('window_hours', 30)} hours. Items: {len(picked)}. "
          f"Outlets answering: {sum(1 for _, i, e in results if e is None and i)}/{len(results)}.\n")
    failed = [(s["name"], e) for s, _, e in results if e]
    empty = [s["name"] for s, i, e in results if not e and not i]
    if failed or empty:
        bits = [f"{n} (error: {e})" for n, e in failed] + [f"{n} (no items in the window)" for n in empty]
        print("Unavailable: " + "; ".join(bits) + "\n")
    else:
        print("Unavailable: none\n")
    if not picked:
        print("NO DATA: every source failed or returned nothing in the window. Say so; do not invent news.")
        return
    by_src = {}
    for s, it in picked:
        by_src.setdefault(s["name"], (s, []))[1].append(it)
    # numbered ids, stable within this run; links go to a sidecar file, not into the prompt
    n = 0
    refs = []
    blocks = {"MX": [], "WORLD": []}
    for region in ("MX", "WORLD"):
        for name, (s, items) in by_src.items():
            if s["region"] != region:
                continue
            blocks[region].append(f"### {name} ({s['note']})")
            for it in items:
                n += 1
                d = it["date"].astimezone(ZoneInfo("America/Mexico_City")).strftime("%m-%d %H:%M") if it["date"] else "n/d"
                line = f"- [{n}] ({d}) {it['title']}"
                if CFG.get("include_summary", True) and it["summary"] and it["summary"][:40].lower() not in it["title"].lower():
                    line += f" -- {it['summary']}"
                blocks[region].append(line)
                refs.append((n, name, d, it["title"], it["link"]))
            blocks[region].append("")
    for region, title in (("MX", "Mexico"), ("WORLD", "World / geopolitics")):
        print(f"## {title}\n")
        print("\n".join(blocks[region]))
    day = f"{local:%Y-%m-%d}"
    try:
        out = Path("/opt/data/notes/Inbox") / f"{day}-news-sources.md"
        lines = [f"# News sources {day}", "", "Reference list for the briefing: id, outlet, time, headline, link.", ""]
        lines += [f"{i}. **{o}** ({d}) {t}  \n   <{l}>" for i, o, d, t, l in refs]
        out.write_text("\n".join(lines) + "\n")
        print(f"Reference file written: Inbox/{day}-news-sources.md")
    except Exception as e:
        print(f"Reference file NOT written: {e}")


if __name__ == "__main__":
    main()
