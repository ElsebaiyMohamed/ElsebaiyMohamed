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


def svg(w, h, body, title, p):
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" '
        f'viewBox="0 0 {w} {h}" role="img" aria-label="{escape(title)}">'
        f'<title>{escape(title)}</title>'
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
        body += (f'<rect x="{32 + i * step:.1f}" y="{132 - bh / 2:.1f}" '
                 f'width="{step * 0.58:.1f}" height="{bh:.1f}" rx="{step * 0.29:.1f}" '
                 f'fill="{p["accent"]}" opacity="{0.35 + 0.6 * n / peak:.2f}"/>')
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
    write("stats.svg", stats(owned, act, language_shares(owned)))
    if act:
        write("rhythm.svg", rhythm(act))


if __name__ == "__main__":
    main()
