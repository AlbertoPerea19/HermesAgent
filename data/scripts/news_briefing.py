#!/usr/bin/env python3
"""Daily politics briefing, built without a model.

Reuses the feed fetcher from news_collect.py, drops sports/entertainment, groups headlines about the same story
across outlets, and writes the full note plus a source list with links. Prints a short summary on stdout
(delivered as is by the no-agent cron job). Standard library only. Always exits 0.
"""
import re
import sys
import unicodedata
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).parent))
import news_collect as nc  # noqa: E402

INBOX = Path("/opt/data/notes/Inbox")
MAX_STORIES = 8          # multi-outlet stories per region in the note
MAX_SINGLES = 5          # single-outlet stories in the note
SUMMARY_STORIES = 3      # per region in the Telegram summary
MAX_CLUSTER = 8

DROP = re.compile(
    r"\b(futbol|liga mx|nfl|nba|mlb|formula 1|tenis|boxeo|beisbol|golf|ufc|olimpic\w*|champions league|premier league|"
    r"la liga|messi|cristiano ronaldo|concierto|cantante|actriz|pelicula|netflix|oscar|grammy|farandula|horoscopo|"
    r"loteria|sorteo|chisme|reality show|telenovela|celebrity|singer|movie|box office|album|taylor swift|soccer|"
    r"football|cricket|rugby|tennis|lottery|horoscope|recipe|receta|pronostico del tiempo|weather forecast|"
    r"gol|goles|jornada \d+ de la liga|entrenador\w*|cruz azul|chivas|pumas|jugadores?|jugadoras?|campeonato|torneo|"
    r"femenil|varonil|medallas?|atleta\w*|partido de futbol)\b"
)
STOP = set(
    "the and for with from that this have has was were are not but his her its their will would could about after "
    "over into than then they them been being more most also says said say new out who how why what when where "
    "los las del las una uno unos unas por con para que como pero sus este esta estos estas sobre entre tras "
    "desde hasta mas muy ser fue son han hay ante contra segun sin tambien durante mientras cada otro otra".split()
)


def strip_suffix(title, note):
    """Google News feeds append ' - Outlet' to every headline; drop it so the same wording is not repeated."""
    if "Google News" in note and " - " in title:
        head, tail = title.rsplit(" - ", 1)
        if len(tail) <= 28 and head:
            return head.strip()
    return title


def norm(text):
    text = unicodedata.normalize("NFKD", text.lower())
    return "".join(c for c in text if not unicodedata.combining(c))


def tokens(title):
    return {t for t in re.findall(r"[a-z0-9]{3,}", norm(title)) if t not in STOP}


def similar(a, b):
    inter = len(a & b)
    if inter < 3:
        return False
    overlap = inter / min(len(a), len(b))
    jaccard = inter / len(a | b)
    return overlap >= 0.5 or jaccard >= 0.3 or (inter >= 4 and overlap >= 0.4)


def cluster(items):
    parent = list(range(len(items)))

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for i in range(len(items)):
        for j in range(i + 1, len(items)):
            if items[i]["outlet"] != items[j]["outlet"] and similar(items[i]["tok"], items[j]["tok"]):
                ri, rj = find(i), find(j)
                if ri != rj:
                    parent[rj] = ri
    groups = {}
    for i in range(len(items)):
        groups.setdefault(find(i), []).append(items[i])
    return list(groups.values())


def representative(group):
    def score(it):
        return sum(len(it["tok"] & o["tok"]) for o in group if o is not it)
    return max(group, key=score)


def main():
    now = datetime.now(timezone.utc)
    local = now.astimezone(ZoneInfo("America/Mexico_City"))
    day = f"{local:%Y-%m-%d}"
    with ThreadPoolExecutor(max_workers=8) as ex:
        results = list(ex.map(nc.fetch, nc.CFG["sources"]))

    answering = sum(1 for _, i, e in results if e is None and i)
    problems = [f"{s['name']} (error: {e})" for s, _, e in results if e] + [
        f"{s['name']} (no items)" for s, i, e in results if not e and not i
    ]
    items, dropped = [], 0
    for src, its, err in results:
        for it in its:
            if DROP.search(norm(it["title"])):
                dropped += 1
                continue
            items.append({"outlet": src["name"], "note": src["note"], "region": src["region"], "title": strip_suffix(it["title"], src["note"]),
                          "link": it["link"], "date": it["date"], "tok": tokens(it["title"])})
    if not items:
        print(f"Politics briefing {day}: no headlines available (every source failed or returned nothing).")
        return

    items.sort(key=lambda x: (x["region"], x["date"] or datetime.min.replace(tzinfo=timezone.utc)), reverse=False)
    for n, it in enumerate(items, 1):
        it["id"] = n

    groups = cluster(items)
    multi, single = [], []
    for g in groups:
        outlets = {i["outlet"] for i in g}
        if len(outlets) >= 2 and len(g) <= MAX_CLUSTER:
            multi.append(g)
        else:
            single.extend(g)

    def newest(g):
        return max((i["date"] or datetime.min.replace(tzinfo=timezone.utc)) for i in g)

    def region_of(g):
        mx = sum(1 for i in g if i["region"] == "MX")
        return "MX" if mx * 2 >= len(g) else "WORLD"

    multi.sort(key=lambda g: (-len({i["outlet"] for i in g}), -newest(g).timestamp()))
    stories = {"MX": [], "WORLD": []}
    for g in multi:
        r = region_of(g)
        if len(stories[r]) < MAX_STORIES:
            stories[r].append(g)

    single.sort(key=lambda i: -(i["date"] or datetime.min.replace(tzinfo=timezone.utc)).timestamp())
    seen, singles = set(), []
    for it in single:  # one per outlet first, newest first, for variety
        if it["outlet"] not in seen and len(singles) < MAX_SINGLES:
            singles.append(it)
            seen.add(it["outlet"])

    described = set()

    def outlet_label(it):
        if it["outlet"] in described:
            return it["outlet"]
        described.add(it["outlet"])
        return f"{it['outlet']} ({it['note']})"

    lines = [f"# Politics briefing {day}", "",
             f"Window: last {nc.CFG.get('window_hours', 30)} h. Outlets answering: {answering}/{len(results)}. "
             f"Headlines kept: {len(items)} (dropped {dropped} sports/entertainment). Headline-level only: no article text was read. "
             f"Grouping is automatic (shared words between headlines), so check a story before relying on it.", ""]
    for region, title in (("MX", "Mexico"), ("WORLD", "World / geopolitics")):
        lines += [f"## {title}: stories covered by 2+ outlets", ""]
        if not stories[region]:
            lines += ["_No story matched across outlets in this window._", ""]
        for k, g in enumerate(stories[region], 1):
            rep = representative(g)
            lines += [f"### {k}. {rep['title']} ({len({i['outlet'] for i in g})} outlets)"]
            for it in sorted(g, key=lambda i: i["outlet"]):
                lines.append(f'- {outlet_label(it)}: "{it["title"]}" [{it["id"]}]')
            lines.append("")
    lines += ["## Single-outlet stories", ""]
    lines += [f'- {outlet_label(i)}: "{i["title"]}" [{i["id"]}]' for i in singles] or ["_None._"]
    lines += ["", "## Sources unavailable", "", "; ".join(problems) if problems else "none", "",
              f"Links for every id: [[{day}-news-sources]]", ""]
    INBOX.mkdir(parents=True, exist_ok=True)
    (INBOX / f"{day}-news-briefing.md").write_text("\n".join(lines), encoding="utf-8")

    src = [f"# News sources {day}", "", "Reference list for the briefing: id, outlet, time, headline, link.", ""]
    for it in sorted(items, key=lambda i: i["id"]):
        d = it["date"].astimezone(ZoneInfo("America/Mexico_City")).strftime("%m-%d %H:%M") if it["date"] else "n/d"
        src.append(f"{it['id']}. **{it['outlet']}** ({d}) {it['title']}  \n   <{it['link']}>")
    (INBOX / f"{day}-news-sources.md").write_text("\n".join(src) + "\n", encoding="utf-8")

    out = [f"Politics briefing {day}"]
    for region, title in (("MX", "Mexico"), ("WORLD", "World")):
        out.append(f"\n{title}")
        top = stories[region][:SUMMARY_STORIES]
        out += [f"• {representative(g)['title']} ({len({i['outlet'] for i in g})} outlets)" for g in top] or [
            "• No story matched across outlets today."]
    out.append(f"\nFull note: Inbox/{day}-news-briefing.md")
    if problems:
        out.append(f"Unavailable sources: {len(problems)}")
    print("\n".join(out))


if __name__ == "__main__":
    main()
