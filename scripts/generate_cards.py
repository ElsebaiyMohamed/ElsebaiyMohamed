#!/usr/bin/env python3
"""Generate profile SVG cards (stats, rhythm, featured repos) from the GitHub API.

Stdlib only. Output goes to assets/ and is committed by the workflow.
Env: GITHUB_TOKEN (needed for activity numbers), GH_USER, FEATURED_REPOS,
EXCLUDE_LANGS, OUT_DIR.
"""
import hashlib
import json
import math
import os
import sys
import textwrap
import urllib.request
from datetime import date, datetime, timedelta, timezone
from html import escape
from pathlib import Path

USER = os.environ.get("GH_USER", "ElsebaiyMohamed")
TOKEN = os.environ.get("GITHUB_TOKEN", "")
FEATURED = [r.strip() for r in os.environ.get(
    "FEATURED_REPOS", "MiniRag_26,Modablag,FluentAI,BnSR").split(",") if r.strip()]
EXCLUDE_LANGS = {l.strip() for l in os.environ.get(
    "EXCLUDE_LANGS", "Jupyter Notebook").split(",") if l.strip()}
OUT = Path(os.environ.get("OUT_DIR", "assets"))

FONT = "'Segoe UI', 'Helvetica Neue', Arial, sans-serif"

# Stats + rhythm: aubergine base, amber signal.
P_STATS = dict(bg="#1A1530", edge="#3A2F66", ink="#F4EFFB", mute="#A99FCB", accent="#F5B85A")

# One identity per project: palette + representative icon.
THEMES = {
    "minirag_26": dict(bg="#0F1E3A", edge="#25427A", mute="#8FA8D3", accent="#5B9DFF", icon="rag"),
    "modablag": dict(bg="#2B1120", edge="#5E2A47", mute="#C79AB0", accent="#FF7FA8", icon="dub"),
    "fluentai": dict(bg="#0E2A33", edge="#1F4D5A", mute="#8FB0B3", accent="#5FD4B0", icon="mic"),
    "bnsr": dict(bg="#0B2B20", edge="#1E5A43", mute="#8FBBA6", accent="#F4606F", icon="bnsr"),
}
FALLBACKS = [
    dict(bg="#1E1740", edge="#3B2F78", mute="#A59BD0", accent="#A78BFA", icon="code"),
    dict(bg="#2A1D0B", edge="#5B4119", mute="#C9AE82", accent="#F5B85A", icon="code"),
    dict(bg="#0F2A2E", edge="#1F5560", mute="#8DB6BC", accent="#4FD1E0", icon="code"),
]

LANG_COLORS = {
    "Python": "#F5B85A", "Java": "#7FB4FF", "MATLAB": "#E8795C", "CSS": "#B79CFF",
    "Shell": "#7ED9A6", "JavaScript": "#F1E05A", "TypeScript": "#6FA8F5",
    "Dockerfile": "#7C9BD1", "HTML": "#F0795A", "C++": "#F27AA6", "Go": "#4FC8E8",
    "Other": "#7C72A8",
}


def lang_color(name):
    return LANG_COLORS.get(name, "#C9A86A")


def theme(name):
    t = THEMES.get(name.lower())
    if t is None:
        t = FALLBACKS[int(hashlib.sha256(name.encode()).hexdigest(), 16) % len(FALLBACKS)]
    return {"ink": "#EEF3F7", **t}


# ---------------------------------------------------------------- GitHub API
def _request(url, payload=None):
    headers = {"Accept": "application/vnd.github+json", "User-Agent": "profile-cards"}
    if TOKEN:
        headers["Authorization"] = f"Bearer {TOKEN}"
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(url, data=data, headers=headers)
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.load(resp)


def rest(path):
    return _request("https://api.github.com" + path)


def gql(query, variables=None):
    res = _request("https://api.github.com/graphql",
                   {"query": query, "variables": variables or {}})
    if "errors" in res:
        raise RuntimeError(res["errors"])
    return res["data"]


def owned_repos():
    repos, page = [], 1
    while True:
        batch = rest(f"/users/{USER}/repos?type=owner&per_page=100&page={page}")
        repos += batch
        if len(batch) < 100:
            return repos
        page += 1


FRAGMENT = ("fragment C on ContributionsCollection{totalCommitContributions "
            "totalPullRequestContributions totalIssueContributions "
            "totalPullRequestReviewContributions "
            "contributionCalendar{weeks{contributionDays{date contributionCount}}}}")


def activity():
    """All-time totals + per-day counts. One aliased query covers every year
    since the account was created (GitHub caps a single range at one year)."""
    if not TOKEN:
        return {}
    head = gql("query($l:String!){user(login:$l){createdAt followers{totalCount}}}",
               {"l": USER})["user"]
    created = datetime.fromisoformat(head["createdAt"].replace("Z", "+00:00"))
    now = datetime.now(timezone.utc)
    parts = []
    for i, year in enumerate(range(created.year, now.year + 1)):
        start = max(created, datetime(year, 1, 1, tzinfo=timezone.utc))
        end = min(now, datetime(year, 12, 31, 23, 59, 59, tzinfo=timezone.utc))
        parts.append(f'y{i}:contributionsCollection(from:"{start:%Y-%m-%dT%H:%M:%SZ}",'
                     f'to:"{end:%Y-%m-%dT%H:%M:%SZ}"){{...C}}')
    data = gql("query($l:String!){user(login:$l){" + " ".join(parts) + "}}" + FRAGMENT,
               {"l": USER})["user"]
    totals = dict(commits=0, prs=0, issues=0, reviews=0)
    days = {}
    for c in data.values():
        totals["commits"] += c["totalCommitContributions"]
        totals["prs"] += c["totalPullRequestContributions"]
        totals["issues"] += c["totalIssueContributions"]
        totals["reviews"] += c["totalPullRequestReviewContributions"]
        for week in c["contributionCalendar"]["weeks"]:
            for d in week["contributionDays"]:
                days[d["date"]] = max(days.get(d["date"], 0), d["contributionCount"])
    return {"created": created, "followers": head["followers"]["totalCount"],
            "totals": totals, "days": days}


def streaks(days):
    longest = run = 0
    prev = None
    for key in sorted(days):
        if days[key] > 0:
            d = date.fromisoformat(key)
            run = run + 1 if prev and (d - prev).days == 1 else 1
            prev = d
            longest = max(longest, run)
    d = datetime.now(timezone.utc).date()
    if days.get(d.isoformat(), 0) == 0:
        d -= timedelta(days=1)
    current = 0
    while days.get(d.isoformat(), 0) > 0:
        current += 1
        d -= timedelta(days=1)
    return current, longest


def language_shares(owned):
    totals = {}
    for r in owned:
        if r.get("archived"):
            continue
        for lang, size in rest(f"/repos/{USER}/{r['name']}/languages").items():
            if lang not in EXCLUDE_LANGS:
                totals[lang] = totals.get(lang, 0) + size
    grand = sum(totals.values()) or 1
    ranked = sorted(totals.items(), key=lambda kv: -kv[1])
    shares = [(n, b * 100 / grand) for n, b in ranked[:5] if b * 100 / grand >= 1]
    other = 100 - sum(p for _, p in shares)
    if other >= 1:
        shares.append(("Other", other))
    return shares


# ------------------------------------------------------------------- drawing
def fmt(n):
    if n is None:
        return "–"
    return n if isinstance(n, str) else f"{n:,}"


def wave(seed, x, y, w, h, p, bars=48):
    """Deterministic waveform: same seed -> same shape."""
    raw = hashlib.shake_256(seed.encode()).digest(bars)
    step = w / bars
    out = []
    for i, b in enumerate(raw):
        taper = math.sin(math.pi * (i + 0.5) / bars) ** 0.7
        bh = max(3.0, h * (0.2 + 0.8 * b / 255) * taper)
        out.append(
            f'<rect x="{x + i * step:.1f}" y="{y + (h - bh) / 2:.1f}" '
            f'width="{step * 0.56:.1f}" height="{bh:.1f}" rx="{step * 0.28:.1f}" '
            f'fill="{p["accent"]}" opacity="{0.25 + 0.65 * taper:.2f}"/>')
    return "".join(out)


def svg(w, h, body, title, p, defs=""):
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" '
        f'viewBox="0 0 {w} {h}" role="img" aria-label="{escape(title)}">'
        f'<title>{escape(title)}</title>'
        f'<defs>{defs}</defs>'
        f'<rect x="0.5" y="0.5" width="{w - 1}" height="{h - 1}" rx="14" '
        f'fill="{p["bg"]}" stroke="{p["edge"]}"/>'
        f'<g font-family="{FONT}">{body}</g></svg>\n')


def mini_bars(a, y, heights, x0=13, gap=5):
    return "".join(
        f'<line x1="{x0 + i * gap}" x2="{x0 + i * gap}" y1="{y - h / 2}" y2="{y + h / 2}" '
        f'stroke="{a}" stroke-width="2.4" stroke-linecap="round"/>'
        for i, h in enumerate(heights))


def icon(kind, p):
    """56x56 representative glyph, drawn in the project's accent."""
    a = p["accent"]
    line = (f'fill="none" stroke="{a}" stroke-width="2.4" '
            f'stroke-linecap="round" stroke-linejoin="round"')
    shapes = {
        # database cylinder: retrieval store
        "rag": (f'<g {line}><ellipse cx="28" cy="15" rx="12" ry="4.5"/>'
                f'<path d="M16 15v24c0 2.5 5.4 4.5 12 4.5s12-2 12-4.5V15"/>'
                f'<path d="M16 27c0 2.5 5.4 4.5 12 4.5s12-2 12-4.5"/></g>'),
        # video frame + audio bars: dubbing
        "dub": (f'<rect x="10" y="9" width="36" height="25" rx="5" {line}/>'
                f'<polygon points="24,15 35,21.5 24,28" fill="{a}"/>'
                + mini_bars(a, 44, [4, 10, 6, 12, 5, 9, 4])),
        # microphone: pronunciation
        "mic": (f'<g {line}><rect x="21" y="8" width="14" height="24" rx="7"/>'
                f'<path d="M14 26a14 14 0 0 0 28 0"/><path d="M28 40v8"/></g>'),
        # red disc over a waveform: Bengali speech
        "bnsr": (f'<circle cx="28" cy="20" r="11" fill="{a}"/>'
                 + mini_bars(a, 43, [4, 10, 6, 12, 5, 9, 4])),
        "code": (f'<g {line}><path d="M20 20l-9 8 9 8"/><path d="M36 20l9 8-9 8"/>'
                 f'<path d="M31 16l-6 24"/></g>'),
    }
    tile = (f'<rect x="0.75" y="0.75" width="54.5" height="54.5" rx="14" fill="{a}" '
            f'fill-opacity="0.12" stroke="{a}" stroke-opacity="0.35"/>')
    return tile + shapes[p["icon"]]


STAR = ('<polygon points="7,0.5 8.9,5 13.5,5.4 10,8.5 11.1,13 7,10.6 2.9,13 4,8.5 '
        '0.5,5.4 5.1,5" fill="{c}"/>')
FORK = ('<g fill="none" stroke="{c}" stroke-width="1.6"><circle cx="2.5" cy="2.5" r="2"/>'
        '<circle cx="11.5" cy="2.5" r="2"/><circle cx="7" cy="13" r="2"/>'
        '<path d="M2.5 4.5v1.5c0 1.5 1 2.5 2.5 2.5h4c1.5 0 2.5-1 2.5-2.5V4.5M7 8.5V11"/></g>')


def card(repo):
    W, H = 480, 190
    name = repo["name"]
    p = theme(name)
    desc = (repo.get("description") or "No description yet.").strip()
    lines = textwrap.wrap(desc, 48)
    if len(lines) > 2:
        lines = [lines[0], lines[1][:45].rstrip(" ,.;") + "…"]

    body = (f'<text x="28" y="46" font-size="20" font-weight="700" '
            f'fill="{p["ink"]}">{escape(name)}</text>')
    for i, line in enumerate(lines):
        body += (f'<text x="28" y="{74 + i * 20}" font-size="13" '
                 f'fill="{p["mute"]}">{escape(line)}</text>')
    body += f'<g transform="translate({W - 28 - 56},22)">{icon(p["icon"], p)}</g>'
    body += wave(name, 28, 108, W - 56, 34, p)

    x, y = 28, 172
    lang = repo.get("language")
    if lang:
        body += (f'<circle cx="{x + 5}" cy="{y - 5}" r="5" fill="{lang_color(lang)}"/>'
                 f'<text x="{x + 16}" y="{y}" font-size="12" fill="{p["ink"]}">'
                 f'{escape(lang)}</text>')
        x += 16 + len(lang) * 7 + 20
    stars = repo["stargazers_count"]
    body += (f'<g transform="translate({x},{y - 12})">{STAR.format(c=p["accent"])}</g>'
             f'<text x="{x + 20}" y="{y}" font-size="12" fill="{p["ink"]}">{stars}</text>')
    x += 20 + len(str(stars)) * 8 + 18
    body += (f'<g transform="translate({x},{y - 13})">{FORK.format(c=p["accent"])}</g>'
             f'<text x="{x + 20}" y="{y}" font-size="12" fill="{p["ink"]}">'
             f'{repo["forks_count"]}</text>')
    body += (f'<text x="{W - 28}" y="{y}" text-anchor="end" font-size="12" '
             f'fill="{p["mute"]}">Updated {repo.get("pushed_at", "")[:10]}</text>')
    return svg(W, H, body, f"{name}: {desc}", p)


def metric_grid(rows, y0, p):
    out = ""
    for r, row in enumerate(rows):
        y = y0 + r * 80
        for i, (label, value) in enumerate(row):
            x = 32 + i * 152
            out += (f'<text x="{x}" y="{y}" font-size="34" font-weight="700" '
                    f'fill="{p["ink"]}">{fmt(value)}</text>'
                    f'<text x="{x}" y="{y + 22}" font-size="12" '
                    f'fill="{p["mute"]}">{escape(label)}</text>')
    return out


def stats(owned, act, langs):
    p = P_STATS
    W, H = 820, 330
    t = act.get("totals", {})
    created = act.get("created")
    longest = streaks(act["days"])[1] if act else None
    stars = sum(r["stargazers_count"] for r in owned)
    forks = sum(r["forks_count"] for r in owned)
    rows = [
        [("Commits", t.get("commits")), ("Pull requests", t.get("prs")),
         ("Issues", t.get("issues")), ("Code reviews", t.get("reviews")),
         ("Stars earned", stars)],
        [("Public repos", len(owned)), ("Forks received", forks),
         ("Followers", act.get("followers")), ("Longest streak (days)", longest),
         ("On GitHub since", str(created.year) if created else None)],
    ]
    sub = (f"All-time totals since {created.year}" if created
           else "Activity totals need a token")
    body = (f'<text x="32" y="48" font-size="22" font-weight="700" fill="{p["ink"]}">'
            f'{escape(USER)}</text>'
            f'<text x="32" y="70" font-size="13" fill="{p["mute"]}">{sub}</text>')
    body += wave(USER, 520, 24, 268, 44, p)
    body += metric_grid(rows, 128, p)

    total_w, x = W - 64, 32.0
    segs = ""
    for name, pct in langs:
        w = total_w * pct / 100
        segs += (f'<rect x="{x:.1f}" y="268" width="{w:.1f}" height="10" '
                 f'fill="{lang_color(name)}"/>')
        x += w
    body += (f'<clipPath id="bar"><rect x="32" y="268" width="{total_w}" height="10" '
             f'rx="5"/></clipPath><g clip-path="url(#bar)">{segs}</g>')
    for i, (name, pct) in enumerate(langs):
        lx = 32 + i * 126
        body += (f'<circle cx="{lx + 5}" cy="303" r="5" fill="{lang_color(name)}"/>'
                 f'<text x="{lx + 16}" y="307" font-size="12" fill="{p["ink"]}">'
                 f'{escape(name)} {pct:.0f}%</text>')
    return svg(W, H, body, f"GitHub totals for {USER}", p)


def rhythm(act):
    """Weekly contributions for the last 52 weeks drawn as a waveform."""
    p = P_STATS
    W, H = 820, 260
    days = act["days"]
    last = sorted(days)[-364:]
    weeks = [sum(days[d] for d in last[i:i + 7]) for i in range(0, len(last), 7)]
    peak = max(weeks) or 1
    step = (W - 64) / len(weeks)
    body = (f'<text x="32" y="48" font-size="22" font-weight="700" fill="{p["ink"]}">'
            f'Contribution rhythm</text>'
            f'<text x="32" y="70" font-size="13" fill="{p["mute"]}">Contributions per week, '
            f'last 52 weeks</text>')
    for i, n in enumerate(weeks):
        bh = max(3.0, 84 * (n / peak) ** 0.6)
        body += bar(32 + i * step, 132 - bh / 2, step * 0.58, bh, step * 0.29,
                    p["accent"], 0.35 + 0.6 * n / peak, i, 132)
    current, longest = streaks(days)
    by_weekday = {}
    for key, n in days.items():
        name = date.fromisoformat(key).strftime("%A")
        by_weekday[name] = by_weekday.get(name, 0) + n
    busiest = max(by_weekday, key=by_weekday.get)
    best_day = max(days, key=days.get)
    items = [("Current streak (days)", current), ("Longest streak (days)", longest),
             ("Busiest weekday", busiest), ("Most in one day", days[best_day]),
             ("Active days", sum(1 for n in days.values() if n))]
    for i, (label, value) in enumerate(items):
        x = 32 + i * 152
        body += (f'<text x="{x}" y="214" font-size="26" font-weight="700" '
                 f'fill="{p["ink"]}">{fmt(value)}</text>'
                 f'<text x="{x}" y="236" font-size="12" fill="{p["mute"]}">{label}</text>')
    return svg(W, H, body, f"Contribution rhythm for {USER}", p)


# ------------------------------------------------- animated charts and banner
SPLINE = "0 0 1 1;0.2 0.8 0.2 1"
RAINBOW = ["#5B9DFF", "#5FD4B0", "#F5B85A", "#FF7FA8", "#F4606F"]  # the project colors


def stops():
    n = len(RAINBOW) - 1
    return "".join(f'<stop offset="{i / n:.2f}" stop-color="{c}"/>'
                   for i, c in enumerate(RAINBOW))


def _timing(i, gap, tail):
    delay = min(i * gap, 1.3)
    total = delay + tail
    return total, f"0;{delay / total:.3f};1"


def bar(x, y, w, h, rx, fill, opacity, i, base):
    """Rounded bar that grows out of `base` (a y coordinate) once on load.
    Final geometry is in the attributes, so viewers without SMIL show the chart."""
    total, kt = _timing(i, 0.03, 0.8)
    common = (f'keyTimes="{kt}" calcMode="spline" keySplines="{SPLINE}" '
              f'dur="{total:.2f}s" fill="freeze"')
    return (f'<rect x="{x:.1f}" y="{y:.1f}" width="{w:.1f}" height="{h:.1f}" rx="{rx:.1f}" '
            f'fill="{fill}" opacity="{opacity:.2f}">'
            f'<animate attributeName="y" values="{base:.1f};{base:.1f};{y:.1f}" {common}/>'
            f'<animate attributeName="height" values="0;0;{h:.1f}" {common}/></rect>')


def breathe(x, cy, w, lo, hi, seed):
    """Looping waveform bar for the banner."""
    dur = 1.4 + (seed % 8) * 0.22
    begin = -(seed % 13) * 0.3
    mid = (lo + hi) / 2
    common = f'dur="{dur:.2f}s" begin="{begin:.1f}s" repeatCount="indefinite"'
    return (f'<rect x="{x:.1f}" y="{cy - mid / 2:.1f}" width="{w}" height="{mid:.1f}" '
            f'rx="{w / 2}" fill="url(#rbv)">'
            f'<animate attributeName="height" values="{lo:.1f};{hi:.1f};{lo:.1f}" {common}/>'
            f'<animate attributeName="y" values="{cy - lo / 2:.1f};{cy - hi / 2:.1f};'
            f'{cy - lo / 2:.1f}" {common}/></rect>')


def header():
    p = P_STATS
    W, H, nw = 900, 240, 500
    roles = ["AI/NLP Engineer",
             "Arabic speech AI: ASR, TTS, speech-to-speech",
             "From research notebook to production API"]
    reveal = (f'dur="2.2s" fill="freeze" calcMode="spline" keyTimes="0;0.15;1" '
              f'keySplines="0 0 1 1;0.4 0 0.2 1"')
    defs = (
        f'<linearGradient id="rbw" gradientUnits="userSpaceOnUse" x1="48" x2="{48 + nw}" '
        f'y1="0" y2="0">{stops()}</linearGradient>'
        f'<linearGradient id="rbv" gradientUnits="userSpaceOnUse" x1="560" x2="860" '
        f'y1="0" y2="0">{stops()}</linearGradient>'
        f'<radialGradient id="glow" cx="0.8" cy="0.5" r="0.7">'
        f'<stop offset="0" stop-color="{p["accent"]}" stop-opacity="0.16"/>'
        f'<stop offset="1" stop-color="{p["accent"]}" stop-opacity="0"/></radialGradient>'
        f'<clipPath id="reveal"><rect x="48" y="60" height="72" width="{nw}">'
        f'<animate attributeName="width" values="0;0;{nw}" {reveal}/></rect></clipPath>')

    body = f'<rect width="{W}" height="{H}" rx="14" fill="url(#glow)"/>'
    body += f'<text x="48" y="50" font-size="18" fill="{p["mute"]}">Hi, I\'m</text>'
    body += (f'<text x="48" y="118" font-size="46" font-weight="800" fill="{p["ink"]}" '
             f'textLength="{nw}" lengthAdjust="spacingAndGlyphs" clip-path="url(#reveal)">'
             f'ElSebaiy Mohammed</text>')
    body += (f'<rect x="48" y="138" height="4" rx="2" width="{nw}" fill="url(#rbw)">'
             f'<animate attributeName="width" values="0;0;{nw}" {reveal}/></rect>')
    body += (f'<rect x="48" y="70" width="3" height="54" rx="1.5" fill="{p["accent"]}">'
             f'<animate attributeName="x" values="48;48;{48 + nw + 6}" {reveal}/>'
             f'<animate attributeName="opacity" values="1;0;1" dur="0.9s" '
             f'repeatCount="indefinite"/></rect>')
    for k, role in enumerate(roles):
        s = k / len(roles)
        keys = [0, s, s + 0.04, s + 0.29, s + 0.33, 1]
        keys = [min(v, 1) for v in keys]
        body += (f'<text x="48" y="182" font-size="22" font-weight="600" fill="{p["accent"]}" '
                 f'opacity="{1 if k == 0 else 0}">{escape(role)}'
                 f'<animate attributeName="opacity" values="0;0;1;1;0;0" '
                 f'keyTimes="{";".join(f"{v:.3f}" for v in keys)}" dur="9s" begin="1.8s" '
                 f'repeatCount="indefinite"/></text>')
    body += (f'<text x="48" y="214" font-size="14" fill="{p["mute"]}">Cairo, Egypt  •  '
             f'Open to remote and Egypt-based roles</text>')
    raw = hashlib.shake_256(b"header").digest(60)
    n = 30
    for i in range(n):
        taper = math.sin(math.pi * (i + 0.5) / n) ** 0.7
        lo = 6 + taper * 14 * raw[i] / 255
        hi = 12 + taper * (52 + 36 * raw[i + 30] / 255)
        body += breathe(560 + i * 10, 120, 5.5, lo, hi, raw[i])
    return svg(W, H, body, "ElSebaiy Mohammed, AI/NLP engineer", p, defs)


def divider():
    W, H, n = 900, 26, 120
    raw = hashlib.shake_256(b"divider").digest(n)
    step = W / n
    bars = ""
    for i, b in enumerate(raw):
        taper = math.sin(math.pi * (i + 0.5) / n) ** 0.6
        bh = max(2.0, 20 * (0.15 + 0.85 * b / 255) * taper)
        bars += (f'<rect x="{i * step:.1f}" y="{(H - bh) / 2:.1f}" width="{step * 0.5:.1f}" '
                 f'height="{bh:.1f}" rx="{step * 0.25:.1f}" fill="url(#d)" opacity="0.85"/>')
    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" '
            f'viewBox="0 0 {W} {H}" role="presentation"><defs>'
            f'<linearGradient id="d" gradientUnits="userSpaceOnUse" x1="0" x2="{W}" '
            f'y1="0" y2="0">{stops()}</linearGradient></defs>{bars}</svg>\n')


def title_block(title, sub, p):
    return (f'<text x="32" y="44" font-size="22" font-weight="700" fill="{p["ink"]}">'
            f'{escape(title)}</text>'
            f'<text x="32" y="66" font-size="13" fill="{p["mute"]}">{escape(sub)}</text>')


def heatmap(days):
    p = P_STATS
    W, H = 820, 232
    today = datetime.now(timezone.utc).date()
    start = today - timedelta(days=(today.weekday() + 1) % 7 + 52 * 7)
    peak = max(days.values()) or 1
    x0, y0, pitch, size = 40, 92, 14, 11
    cells, total = "", 0
    for col in range(53):
        first = start + timedelta(days=col * 7)
        if first.day <= 7:
            cells += (f'<text x="{x0 + col * pitch}" y="84" font-size="11" '
                      f'fill="{p["mute"]}">{first:%b}</text>')
        tshift, kt = _timing(col, 0.025, 0.4)
        for row in range(7):
            d = first + timedelta(days=row)
            if d > today:
                continue
            n = days.get(d.isoformat(), 0)
            total += n
            if n == 0:
                fill, fo = "#2B2450", 1
            else:
                lvl = min(4, 1 + int(4 * (n / peak) ** 0.6))
                fill, fo = p["accent"], {1: 0.3, 2: 0.55, 3: 0.8, 4: 1}[lvl]
            cells += (f'<rect x="{x0 + col * pitch}" y="{y0 + row * pitch}" width="{size}" '
                      f'height="{size}" rx="3" fill="{fill}" fill-opacity="{fo}">'
                      f'<animate attributeName="opacity" values="0;0;1" keyTimes="{kt}" '
                      f'dur="{tshift:.2f}s" fill="freeze"/></rect>')
    lx = W - 32 - 150
    legend = f'<text x="{lx}" y="217" font-size="11" fill="{p["mute"]}">Less</text>'
    for k, (fill, fo) in enumerate([("#2B2450", 1)] + [(p["accent"], o) for o in (.3, .55, .8, 1)]):
        legend += (f'<rect x="{lx + 32 + k * 14}" y="207" width="{size}" height="{size}" '
                   f'rx="3" fill="{fill}" fill-opacity="{fo}"/>')
    legend += f'<text x="{lx + 32 + 5 * 14 + 4}" y="217" font-size="11" fill="{p["mute"]}">More</text>'
    body = title_block("Contribution calendar", f"{total:,} contributions in the last year", p)
    return svg(W, H, body + cells + legend, f"Contribution calendar for {USER}", p)


def weekday_chart(days):
    p = P_STATS
    W, H = 400, 250
    names = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    sums = [0] * 7
    for key, n in days.items():
        sums[date.fromisoformat(key).weekday()] += n
    peak = max(sums) or 1
    base, pitch = 196, (W - 64) / 7
    body = title_block("Weekday pattern", "Total contributions by day of week", p)
    for i, n in enumerate(sums):
        h = max(3.0, 94 * (n / peak))
        x = 32 + i * pitch + (pitch - 30) / 2
        top = n == peak
        body += bar(x, base - h, 30, h, 8, p["accent"], 1.0 if top else 0.5, i, base)
        body += (f'<text x="{x + 15:.1f}" y="{base - h - 7:.1f}" text-anchor="middle" '
                 f'font-size="11" fill="{p["ink"] if top else p["mute"]}">{n:,}</text>'
                 f'<text x="{x + 15:.1f}" y="217" text-anchor="middle" font-size="12" '
                 f'fill="{p["mute"]}">{names[i]}</text>')
    return svg(W, H, body, f"Weekday pattern for {USER}", p)


def languages_donut(langs):
    p = P_STATS
    W, H = 400, 250
    cx, cy, r, sw = 105, 142, 62, 24
    circ = 2 * math.pi * r
    body = title_block("Languages", "Share of code in public repos", p)
    start = 0.0
    for i, (name, pct) in enumerate(langs):
        seg = circ * pct / 100
        dash = max(seg - (2 if len(langs) > 1 else 0), 0.1)
        total, kt = _timing(i, 0.25, 0.9)
        body += (f'<circle cx="{cx}" cy="{cy}" r="{r}" fill="none" stroke="{lang_color(name)}" '
                 f'stroke-width="{sw}" stroke-dasharray="{dash:.2f} {circ:.2f}" '
                 f'stroke-dashoffset="{-start:.2f}" transform="rotate(-90 {cx} {cy})">'
                 f'<animate attributeName="stroke-dasharray" '
                 f'values="0 {circ:.2f};0 {circ:.2f};{dash:.2f} {circ:.2f}" keyTimes="{kt}" '
                 f'dur="{total:.2f}s" fill="freeze"/></circle>')
        start += seg
    if langs:
        top, pct = langs[0]
        body += (f'<text x="{cx}" y="{cy + 2}" text-anchor="middle" font-size="22" '
                 f'font-weight="700" fill="{p["ink"]}">{pct:.0f}%</text>'
                 f'<text x="{cx}" y="{cy + 20}" text-anchor="middle" font-size="11" '
                 f'fill="{p["mute"]}">{escape(top)}</text>')
    for i, (name, pct) in enumerate(langs):
        y = 112 + i * 24
        body += (f'<circle cx="222" cy="{y - 4}" r="5" fill="{lang_color(name)}"/>'
                 f'<text x="236" y="{y}" font-size="13" fill="{p["ink"]}">{escape(name)}</text>'
                 f'<text x="368" y="{y}" text-anchor="end" font-size="13" '
                 f'fill="{p["mute"]}">{pct:.0f}%</text>')
    return svg(W, H, body, f"Language share for {USER}", p)


def monthly_chart(days):
    p = P_STATS
    W, H, base = 820, 230, 190
    sums = {}
    for key, n in days.items():
        sums[key[:7]] = sums.get(key[:7], 0) + n
    today = datetime.now(timezone.utc).date()
    y, m, keys = today.year, today.month, []
    for _ in range(36):
        keys.append(f"{y}-{m:02d}")
        m -= 1
        if m == 0:
            y, m = y - 1, 12
    keys.reverse()
    vals = [sums.get(k, 0) for k in keys]
    peak = max(vals) or 1
    step = (W - 64) / len(keys)
    body = title_block("Monthly contributions", "Last 36 months", p)
    for i, (k, n) in enumerate(zip(keys, vals)):
        h = max(3.0, 100 * (n / peak) ** 0.7)
        x = 32 + i * step
        body += bar(x, base - h, step * 0.55, h, step * 0.27, p["accent"],
                    0.4 + 0.6 * n / peak, i, base)
        if n == peak:
            body += (f'<text x="{x + step * 0.27:.1f}" y="{base - h - 8:.1f}" '
                     f'text-anchor="middle" font-size="11" fill="{p["ink"]}">{n:,}</text>')
        if k.endswith("-01"):
            body += (f'<text x="{x:.1f}" y="212" font-size="12" '
                     f'fill="{p["mute"]}">{k[:4]}</text>')
    return svg(W, H, body, f"Monthly contributions for {USER}", p)


def write(name, content):
    path = OUT / name
    if not path.exists() or path.read_text(encoding="utf-8") != content:
        path.write_text(content, encoding="utf-8")
        print("updated", path)


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    repos = owned_repos()
    by_name = {r["name"].lower(): r for r in repos}
    for name in FEATURED:
        repo = by_name.get(name.lower())
        if repo is None:
            print(f"skip {name}: repo not found", file=sys.stderr)
            continue
        write(f"featured-{repo['name'].lower()}.svg", card(repo))
    owned = [r for r in repos if not r["fork"]]
    act = activity()
    langs = language_shares(owned)
    write("header.svg", header())
    write("divider.svg", divider())
    write("stats.svg", stats(owned, act, langs))
    write("languages.svg", languages_donut(langs))
    if act:
        write("rhythm.svg", rhythm(act))
        write("heatmap.svg", heatmap(act["days"]))
        write("weekday.svg", weekday_chart(act["days"]))
        write("monthly.svg", monthly_chart(act["days"]))


if __name__ == "__main__":
    main()
