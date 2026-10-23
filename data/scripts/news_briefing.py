#!/usr/bin/env python3
"""Daily politics briefing, built without a model.

Reuses the feed fetcher from news_collect.py, keeps political/government/security/economy/geopolitics headlines,
groups headlines about the same story across outlets, and writes the full note plus a source list with links.
Prints a short, scannable Telegram message on stdout (delivered as is by the no-agent cron job; Hermes converts the
markdown to Telegram format). Standard library only. Always exits 0.
"""
import json
import os
import re
import sys
import unicodedata
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).parent))
import news_collect as nc  # noqa: E402

INBOX = Path(os.environ.get("BRIEFING_INBOX", "/opt/data/notes/Inbox"))
MAX_STORIES = 8          # stories per region in the note
MAX_SINGLES = 6          # single-outlet stories in the note
TG_STORIES = 6           # stories per region in the Telegram message
TG_LIMIT = 3950          # Telegram allows 4096 characters
MAX_CLUSTER = 8

DROP = re.compile(
    r"\b(futbol|liga mx|nfl|nba|mlb|formula 1|tenis|boxeo|beisbol|golf|ufc|olimpic\w*|champions league|premier league|"
    r"la liga|messi|cristiano ronaldo|concierto|cantante|actriz|pelicula|netflix|oscar|grammy|farandula|horoscopo|"
    r"loteria|sorteo|chisme|reality show|telenovela|celebrity|singer|movie|box office|album|taylor swift|soccer|"
    r"football|cricket|rugby|tennis|lottery|horoscope|recipe|receta|pronostico del tiempo|weather forecast|"
    r"gol|goles|jornada \d+ de la liga|entrenador\w*|cruz azul|chivas|pumas|jugadores?|jugadoras?|campeonato|torneo|"
    r"femenil|varonil|medallas?|atleta\w*|partido de futbol|"
    r"desfile\w*|alebrije\w*|cartelera|horarios?|ruta completa|festival\w*|exposicion|museo|gastronomi\w*|turismo|"
    r"lluvias?|clima|pronostico|viral|tiktok|influencer|youtuber)\b"
)
POLITICAL = re.compile(
    r"\b(gobierno|president\w*|sheinbaum|trump|biden|congreso|senado|senador\w*|diputad\w*|morena|pan|pri|prd|ine|"
    r"eleccion\w*|electoral|reforma|ley|leyes|tribunal|corte|scjn|fiscal\w*|fgr|justicia|juez\w*|jueza|sentenc\w*|"
    r"vinculan|detenid\w*|crimen|cartel\w*|narco\w*|seguridad|guardia nacional|ejercito|militar\w*|guerra|ataque\w*|"
    r"sancion\w*|arancel\w*|tmec|comercio|economia|inflacion|banxico|hacienda|presupuesto|deuda|onu|otan|nato|"
    r"union europea|ucrania|rusia|china|israel|gaza|palestin\w*|iran|venezuela|cuba|eeuu|estados unidos|casa blanca|"
    r"white house|minister|ministro|parliament|parlamento|government|election|sanction\w*|tariff\w*|war|ceasefire|"
    r"treaty|tratado|court|police|policia|protest\w*|manifestaci\w*|migra\w*|immigra\w*|border|frontera|diplomat\w*|"
    r"embajad\w*|summit|cumbre|papa|pope|vaticano|senate|congress|republican\w*|democrat\w*|kremlin|putin|zelensk\w*|"
    r"netanyahu|macron|starmer|modi|xi jinping|erdogan|milei|lula|petro|maduro|ebrard|de la fuente|"
    r"corrupci\w*|desaparecid\w*|feminicidio\w*|homicidio\w*|secuestro\w*|aftosa|ganado|exportaci\w*|sanidad)\b"
)
STOP = set(
    "the and for with from that this have has was were are not but his her its their will would could about after "
    "over into than then they them been being more most also says said say new out who how why what when where "
    "los las del las una uno unos unas por con para que como pero sus este esta estos estas sobre entre tras "
    "desde hasta mas muy ser fue son han hay ante contra segun sin tambien durante mientras cada otro otra".split()
)
# Approximate editorial lean (common media-bias consensus, not a measurement). Shown to the reader and the model.
LEAN = {
    "La Jornada": "izquierda, afín al gobierno", "Proceso": "izquierda crítica", "Aristegui Noticias": "izquierda independiente",
    "Animal Politico": "centro-izquierda", "El Pais Mexico": "centro-izquierda", "Milenio": "centro",
    "El Financiero": "centro empresarial", "Expansion Politica": "centro empresarial", "Mexico News Daily": "centro",
    "El Universal": "centro-derecha", "Reforma": "derecha liberal, crítico del gobierno", "Infobae Mexico": "centro-derecha",
    "Infobae America": "centro-derecha", "Reuters": "agencia", "AP": "agencia", "BBC World": "centro",
    "Al Jazeera": "financiado por Qatar", "DW": "centro", "France 24": "centro", "The Guardian": "centro-izquierda",
    "NPR World": "centro-izquierda", "SCMP": "propiedad de Alibaba, mira a China", "Times of India": "centro-derecha",
    "The Hindu": "centro-izquierda", "Foreign Policy": "centro liberal", "Crisis Group": "ONG de conflictos",
}
WEEKDAYS = ["lun", "mar", "mié", "jue", "vie", "sáb", "dom"]
MONTHS = ["ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic"]
MIN_DT = datetime.min.replace(tzinfo=timezone.utc)


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


def context_line(group, title):
    """One line of extra context from the feeds' own descriptions, only when it adds something new."""
    best = ""
    ttok = tokens(title)
    for it in group:
        s = (it.get("summary") or "").strip()
        if len(s) < 50 or "google news" in s.lower():
            continue
        stok = tokens(s)
        if stok and len(stok & ttok) / len(stok | ttok) >= 0.6:
            continue  # restates the headline
        if len(s) > len(best):
            best = s
    return best[:170].rstrip(" ,;:") + ("…" if len(best) > 170 else "") if best else ""


def esc(text):
    """Neutralize characters that would be read as markdown (Hermes escapes everything else itself)."""
    return text.translate(str.maketrans({"*": "", "_": " ", "`": "'", "[": "(", "]": ")"}))


def outlets_of(group):
    seen = []
    for it in sorted(group, key=lambda i: i["outlet"]):
        if it["outlet"] not in seen:
            seen.append(it["outlet"])
    return seen


def api_key():
    """Cron scripts do not inherit secrets, so fall back to reading the key from the agent's own .env file."""
    key = os.environ.get("OPENROUTER_API_KEY")
    if key:
        return key
    try:
        for line in Path(os.environ.get("HERMES_HOME", "/opt/data"), ".env").read_text().splitlines():
            if line.startswith("OPENROUTER_API_KEY="):
                return line.split("=", 1)[1].strip().strip("\"'")
    except OSError:
        pass
    return None


def summarize(top, singles):
    """One cheap model call that turns grouped headlines into short Spanish summaries.

    Returns {"stories": {first item id of the group: {title, body}}, "singles": [str]} or None on any failure,
    in which case the caller falls back to the model-free format.
    """
    key = api_key()
    if not key:
        return None
    payload = []
    for g in (g for r in top.values() for g in r):
        payload.append({"id": g[0]["id"], "headlines": [f'{i["outlet"]} [{LEAN.get(i["outlet"], "?")}]: {i["title"]}' for i in g][:6],
                        "snippets": [(i.get("summary") or "")[:220] for i in g if len(i.get("summary") or "") > 50][:2]})
    if not payload:
        return None
    single_lines = [f'{i["outlet"]}: {i["title"]}' for i in singles]
    system = (
        "You write a Spanish (Mexico) news digest for one reader from raw headlines and snippets. Use ONLY facts present "
        "in the input; never add background, titles, roles (e.g. president, former), numbers or names that are not there. If outlets disagree, say so. "
        "Return JSON: {\"stories\":[{\"id\":int,\"title\":str,\"body\":str,\"framing\":str}],\"singles\":[str]}. "
        "title: neutral Spanish headline, max 90 chars, no outlet names. body: 2 plain sentences, max 230 chars: what "
        "happened, then what is pending (only if the input supports it). framing: ONE sentence, max 200 chars, contrasting how "
        "outlets of different lean present it, naming them (e.g. 'La Jornada lo enmarca como X; Reforma destaca Y'), based only on "
        "their headlines; if they frame it alike or the input does not show it, return an empty string. Do not guess intent. "
        "singles: one Spanish line "
        "(max 110 chars) per single-outlet input, same order, WITHOUT the outlet name. "
        "No markdown, no emojis."
    )
    user = "STORIES:\n" + json.dumps(payload, ensure_ascii=False) + "\nSINGLES:\n" + json.dumps(single_lines, ensure_ascii=False)
    body = json.dumps({"model": os.environ.get("BRIEFING_MODEL", "qwen/qwen3.7-flash"), "temperature": 0.2,
                       "max_tokens": 4000, "reasoning": {"enabled": False}, "response_format": {"type": "json_object"},
                       "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}]}).encode()
    try:
        req = urllib.request.Request("https://openrouter.ai/api/v1/chat/completions", data=body,
                                     headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=60) as r:
            text = json.load(r)["choices"][0]["message"]["content"]
        data = json.loads(text)
        out = {}
        for s in data["stories"]:
            if isinstance(s.get("id"), int) and str(s.get("title", "")).strip() and str(s.get("body", "")).strip():
                out[s["id"]] = {"title": esc(s["title"].strip()), "body": esc(s["body"].strip()), "framing": esc(str(s.get("framing", "")).strip())}
        if not out:
            return None
        return {"stories": out, "singles": [esc(str(t).strip()) for t in data.get("singles", [])][:3]}
    except Exception as e:
        if os.environ.get("BRIEFING_DEBUG"):
            print(f"summarize failed: {e!r}", file=sys.stderr)
        return None


def cluster_with_model(items):
    """Ask the model to group headlines about the same event (any language) and write the summaries in one call.

    Returns (stories {"MX": [group, ...], "WORLD": [...]}, ai dict shaped like summarize()'s) or None on failure.
    """
    key = api_key()
    cands = sorted((i for i in items if i["political"]), key=lambda i: i["date"] or MIN_DT, reverse=True)[:170]
    if not key or len(cands) < 6:
        return None
    by_id = {i["id"]: i for i in cands}
    lines = [f'{i["id"]}|{i["outlet"]} [{LEAN.get(i["outlet"], "?")}]|{i["title"][:150]}' for i in cands]
    system = (
        "You build a Spanish (Mexico) political news digest for one reader from headlines (id|outlet [lean]|headline), "
        "in Spanish and English. Group headlines that report the SAME single event, even across languages. Never merge different events or countries into one group; if unsure, leave the headline out. The title and body must describe exactly one event. Keep only groups with "
        "at least 2 different outlets, preferring groups whose outlets have different lean. Pick up to 7 groups about Mexico "
        "(region MX) and up to 7 about the rest of the world (region WORLD), ordered by importance (government, security, "
        "economy, conflicts, diplomacy) and then by breadth of coverage. Ignore sports and entertainment. Use ONLY facts "
        "present in the headlines; never add background, titles, roles, numbers or names that are not there. "
        "Return JSON {\"stories\":[{\"region\":\"MX\"|\"WORLD\",\"ids\":[int],\"title\":str,\"body\":str,\"framing\":str}]}. "
        "title: neutral Spanish headline, max 90 chars, no outlet names. body: 2 plain sentences, max 220 chars: what happened, "
        "then what is pending (only if the input supports it). framing: ONE sentence, max 200 chars, ONLY when outlets of "
        "different lean visibly present the story differently (emphasis, blame, word choice), naming them, e.g. "
        "'La Jornada subraya X; Reforma destaca Y'. Otherwise return an empty string; never invent a contrast. No markdown, no emojis."
    )
    body = json.dumps({"model": os.environ.get("BRIEFING_MODEL", "qwen/qwen3.7-flash"), "temperature": 0.2,
                       "max_tokens": 6000, "reasoning": {"enabled": False}, "response_format": {"type": "json_object"},
                       "messages": [{"role": "system", "content": system}, {"role": "user", "content": "\n".join(lines)}]}).encode()
    try:
        req = urllib.request.Request("https://openrouter.ai/api/v1/chat/completions", data=body,
                                     headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=90) as r:
            data = json.loads(json.load(r)["choices"][0]["message"]["content"])
        stories, texts, used = {"MX": [], "WORLD": []}, {}, set()
        for st in data["stories"]:
            ids = [i for i in dict.fromkeys(st.get("ids", [])) if i in by_id and i not in used]
            group = [by_id[i] for i in ids]
            region = st.get("region")
            if region not in stories or len({g["outlet"] for g in group}) < 2 or len(stories[region]) >= 7:
                continue
            if not str(st.get("title", "")).strip() or not str(st.get("body", "")).strip():
                continue
            used.update(ids)
            stories[region].append(group)
            texts[group[0]["id"]] = {"title": esc(st["title"].strip()), "body": esc(st["body"].strip()),
                                     "framing": esc(str(st.get("framing", "")).strip())}
        if not texts:
            return None
        return stories, {"stories": texts, "singles": []}
    except Exception as e:
        if os.environ.get("BRIEFING_DEBUG"):
            print(f"cluster_with_model failed: {e!r}", file=sys.stderr)
        return None


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
            title = strip_suffix(it["title"], src["note"])
            if DROP.search(norm(title)):
                dropped += 1
                continue
            items.append({"outlet": src["name"], "note": src["note"], "region": src["region"], "title": title,
                          "link": it["link"], "date": it["date"], "summary": it.get("summary", ""),
                          "tok": tokens(title), "political": bool(POLITICAL.search(norm(title)))})
    if not items:
        print(f"Resumen político {day}: no hay titulares disponibles (todas las fuentes fallaron o vinieron vacías).")
        return

    items.sort(key=lambda x: (x["region"], x["date"] or MIN_DT))
    for n, it in enumerate(items, 1):
        it["id"] = n

    def newest(g):
        return max((i["date"] or MIN_DT) for i in g)

    def region_of(g):
        mx = sum(1 for i in g if i["region"] == "MX")
        return "MX" if mx * 2 >= len(g) else "WORLD"

    def is_political(g):
        return any(i["political"] for i in g)

    multi, single = [], []
    for g in cluster(items):
        outlets = {i["outlet"] for i in g}
        if len(outlets) >= 2 and len(g) <= MAX_CLUSTER:
            # 3+ outlets is news by itself; 2 outlets must also look political
            if len(outlets) >= 3 or is_political(g):
                multi.append(g)
        elif is_political(g):
            single.extend(g)

    def diversity(g):
        return len({LEAN.get(i["outlet"], i["outlet"]) for i in g})

    multi.sort(key=lambda g: (-diversity(g), -len({i["outlet"] for i in g}), -newest(g).timestamp()))
    stories = {"MX": [], "WORLD": []}
    for g in multi:
        r = region_of(g)
        if len(stories[r]) < MAX_STORIES:
            stories[r].append(g)

    single.sort(key=lambda i: -(i["date"] or MIN_DT).timestamp())
    seen, singles = set(), []
    for it in single:  # one per outlet, newest first, for variety
        if it["outlet"] not in seen and len(singles) < MAX_SINGLES:
            singles.append(it)
            seen.add(it["outlet"])

    preai = cluster_with_model(items)
    if preai:
        stories = preai[0]

    # ---- full note (English, for the notes folder) ----
    described = set()

    def outlet_label(it):
        if it["outlet"] in described:
            return it["outlet"]
        described.add(it["outlet"])
        return f"{it['outlet']} ({it['note']})"

    lines = [f"# Politics briefing {day}", "",
             f"Window: last {nc.CFG.get('window_hours', 30)} h. Outlets answering: {answering}/{len(results)}. "
             f"Headlines kept: {len(items)} (dropped {dropped} sports/entertainment/lifestyle). Headline-level only: no article "
             f"text was read. Grouping is automatic (shared words between headlines), so check a story before relying on it.", ""]
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

    # ---- Telegram message (Spanish labels, scannable) ----
    def story_block(k, g):
        rep = representative(g)
        names = outlets_of(g)
        ctx = context_line(g, rep["title"])
        out = [f"**{k}. {esc(rep['title'])}**"]
        if ctx:
            out.append(esc(ctx))
        out.append(f"{len(names)} medios: {' · '.join(esc(n) for n in names[:5])}" + (" …" if len(names) > 5 else ""))
        if rep.get("link"):
            out.append(f"[Abrir nota]({rep['link']})")
        return "\n".join(out)

    def build(limit):
        parts = [f"**Resumen político · {WEEKDAYS[local.weekday()]} {local.day} {MONTHS[local.month - 1]}**"]
        for region, header in (("MX", "🇲🇽 México"), ("WORLD", "🌍 Mundo")):
            parts.append(f"\n**{header}**")
            top = stories[region][:limit]
            if not top:
                parts.append("Sin historias repetidas entre medios hoy.")
            parts += [story_block(k, g) + "\n" for k, g in enumerate(top, 1)]
        if singles:
            parts.append("**Otras señales (un solo medio)**")
            parts += [f"• {esc(i['title'])} — {esc(i['outlet'])}" for i in singles[:3]]
        foot = f"\nNota completa: Inbox/{day}-news-briefing.md"
        if problems:
            foot += f"\nFuentes sin respuesta: {len(problems)}"
        foot += "\n(Formato básico: el resumen con IA no estuvo disponible hoy)"
        parts.append(foot)
        return "\n".join(parts)

    def build_ai(ai, limit):
        """Plain text on purpose: the cron path does not render markdown, so no bold or link syntax."""
        parts = [f"📰 Resumen político · {WEEKDAYS[local.weekday()]} {local.day} {MONTHS[local.month - 1]}"]
        for region, header in (("MX", "🇲🇽 MÉXICO"), ("WORLD", "🌍 MUNDO")):
            rows = [(g, ai["stories"].get(g[0]["id"])) for g in stories[region][:limit]]
            rows = [(g, a) for g, a in rows if a]
            if not rows:
                continue
            parts.append(f"\n{header}")
            for k, (g, a) in enumerate(rows, 1):
                rep = representative(g)
                block = [f"\n{k}. {a['title']}", a["body"], f"Fuentes: {' · '.join(f'{n} ({LEAN[n]})' if n in LEAN and LEAN[n] != 'agencia' else n for n in outlets_of(g)[:4])}"]
                if a.get("framing"):
                    block.insert(2, f"🔎 {a['framing']}")
                link = next((i["link"] for i in sorted(g, key=lambda i: "google" in i["link"]) if i.get("link")), "")
                if link and "news.google.com" not in link:
                    block.append(link)
                parts.append("\n".join(block))
        if ai["singles"]:
            parts.append("\n👀 TAMBIÉN")
            parts += [f"• {t} — {singles[n]['outlet']}" for n, t in enumerate(ai["singles"][:len(singles)])]
        foot = f"\nNota completa: Inbox/{day}-news-briefing.md"
        if problems:
            foot += f"\nFuentes sin respuesta: {len(problems)}"
        parts.append(foot)
        return "\n".join(parts)

    limit = TG_STORIES
    ai = preai[1] if preai else summarize({r: stories[r][:limit] for r in stories}, singles[:3])
    if ai:
        message = build_ai(ai, limit)
        while len(message) > TG_LIMIT and limit > 1:
            limit -= 1
            message = build_ai(ai, limit)
    else:
        message = build(limit)
        while len(message) > TG_LIMIT and limit > 1:
            limit -= 1
            message = build(limit)
    print(message)


if __name__ == "__main__":
    main()
