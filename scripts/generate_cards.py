#!/usr/bin/env python3
"""Generate profile SVG cards (stats + featured repos) from the GitHub API.

Stdlib only. Output goes to assets/ and is committed by the workflow.
Env: GITHUB_TOKEN (needed for the activity numbers), GH_USER, FEATURED_REPOS,
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

# Deep sea base, mint "signal" accent. Waveform motif = speech audio.
C = dict(bg="#0E2A33", edge="#1F4D5A", ink="#EAF2F0", mute="#8FB0B3", accent="#5FD4B0")
FONT = "'Segoe UI', 'Helvetica Neue', Arial, sans-serif"
LANG_COLORS = {
    "Python": "#5FD4B0", "JavaScript": "#F1E05A", "TypeScript": "#6FA8F5",
    "Shell": "#89E051", "Dockerfile": "#6E94A0", "HTML": "#F0795A",
    "CSS": "#A58BDB", "C++": "#F27AA6", "Go": "#4FC8E8", "Other": "#5C7F88",
}


def lang_color(name):
    return LANG_COLORS.get(name, "#C9A86A")


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


def gql(query, variables=None):
    res = _request("https://api.github.com/graphql",
                   {"query": query, "variables": variables or {}})
    if "errors" in res:
        raise RuntimeError(res["errors"])
    return res["data"]


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


def fmt(n):
    if n is None:
        return "–"
    return n if isinstance(n, str) else f"{n:,}"


def wave(seed, x, y, w, h, bars=48):
    """Deterministic waveform: same repo name -> same shape."""
    raw = hashlib.shake_256(seed.encode()).digest(bars)
    step = w / bars
    out = []
    for i, b in enumerate(raw):
        taper = math.sin(math.pi * (i + 0.5) / bars) ** 0.7
        bh = max(3.0, h * (0.2 + 0.8 * b / 255) * taper)
        out.append(
            f'<rect x="{x + i * step:.1f}" y="{y + (h - bh) / 2:.1f}" '
            f'width="{step * 0.56:.1f}" height="{bh:.1f}" rx="{step * 0.28:.1f}" '
            f'fill="{C["accent"]}" opacity="{0.25 + 0.65 * taper:.2f}"/>')
    return "".join(out)


def svg(w, h, body, title):
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" '
        f'viewBox="0 0 {w} {h}" role="img" aria-label="{escape(title)}">'
        f'<title>{escape(title)}</title>'
        f'<rect x="0.5" y="0.5" width="{w - 1}" height="{h - 1}" rx="14" '
        f'fill="{C["bg"]}" stroke="{C["edge"]}"/>'
        f'<g font-family="{FONT}">{body}</g></svg>\n')


STAR = ('<polygon points="7,0.5 8.9,5 13.5,5.4 10,8.5 11.1,13 7,10.6 2.9,13 4,8.5 '
        '0.5,5.4 5.1,5" fill="{c}"/>')
FORK = ('<g fill="none" stroke="{c}" stroke-width="1.6"><circle cx="2.5" cy="2.5" r="2"/>'
        '<circle cx="11.5" cy="2.5" r="2"/><circle cx="7" cy="13" r="2"/>'
        '<path d="M2.5 4.5v1.5c0 1.5 1 2.5 2.5 2.5h4c1.5 0 2.5-1 2.5-2.5V4.5M7 8.5V11"/></g>')


def card(repo):
    W, H = 480, 190
    name = repo["name"]
    desc = (repo.get("description") or "No description yet.").strip()
    lines = textwrap.wrap(desc, 50)
    if len(lines) > 2:
        lines = [lines[0], lines[1][:47].rstrip(" ,.;") + "…"]

    body = (f'<text x="28" y="46" font-size="20" font-weight="700" '
            f'fill="{C["ink"]}">{escape(name)}</text>')
    for i, line in enumerate(lines):
        body += (f'<text x="28" y="{74 + i * 20}" font-size="13" '
                 f'fill="{C["mute"]}">{escape(line)}</text>')
    body += wave(name, 28, 108, W - 56, 34)

    x, y = 28, 172
    lang = repo.get("language")
    if lang:
        body += (f'<circle cx="{x + 5}" cy="{y - 5}" r="5" fill="{lang_color(lang)}"/>'
                 f'<text x="{x + 16}" y="{y}" font-size="12" fill="{C["ink"]}">'
                 f'{escape(lang)}</text>')
        x += 16 + len(lang) * 7 + 20
    stars = repo["stargazers_count"]
    body += (f'<g transform="translate({x},{y - 12})">{STAR.format(c=C["accent"])}</g>'
             f'<text x="{x + 20}" y="{y}" font-size="12" fill="{C["ink"]}">{stars}</text>')
    x += 20 + len(str(stars)) * 8 + 18
    body += (f'<g transform="translate({x},{y - 13})">{FORK.format(c=C["accent"])}</g>'
             f'<text x="{x + 20}" y="{y}" font-size="12" fill="{C["ink"]}">'
             f'{repo["forks_count"]}</text>')
    body += (f'<text x="{W - 28}" y="{y}" text-anchor="end" font-size="12" '
             f'fill="{C["mute"]}">Updated {repo.get("pushed_at", "")[:10]}</text>')
    return svg(W, H, body, f"{name}: {desc}")


def metric_grid(rows, y0):
    out = ""
    for r, row in enumerate(rows):
        y = y0 + r * 80
        for i, (label, value) in enumerate(row):
            x = 32 + i * 152
            out += (f'<text x="{x}" y="{y}" font-size="34" font-weight="700" '
                    f'fill="{C["ink"]}">{fmt(value)}</text>'
                    f'<text x="{x}" y="{y + 22}" font-size="12" '
                    f'fill="{C["mute"]}">{escape(label)}</text>')
    return out


def stats(owned, act, langs):
    W, H = 820, 330
    t = act.get("totals", {})
    created = act.get("created")
    current, longest = streaks(act["days"]) if act else (None, None)
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
    body = (f'<text x="32" y="48" font-size="22" font-weight="700" fill="{C["ink"]}">'
            f'{escape(USER)}</text>'
            f'<text x="32" y="70" font-size="13" fill="{C["mute"]}">{sub}</text>')
    body += wave(USER, 520, 24, 268, 44)
    body += metric_grid(rows, 128)

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
                 f'<text x="{lx + 16}" y="307" font-size="12" fill="{C["ink"]}">'
                 f'{escape(name)} {pct:.0f}%</text>')
    return svg(W, H, body, f"GitHub totals for {USER}")


def rhythm(act):
    """Weekly contributions for the last 52 weeks drawn as a waveform."""
    W, H = 820, 260
    days = act["days"]
    last = sorted(days)[-364:]
    weeks = [sum(days[d] for d in last[i:i + 7]) for i in range(0, len(last), 7)]
    peak = max(weeks) or 1
    step = (W - 64) / len(weeks)
    body = (f'<text x="32" y="48" font-size="22" font-weight="700" fill="{C["ink"]}">'
            f'Contribution rhythm</text>'
            f'<text x="32" y="70" font-size="13" fill="{C["mute"]}">Contributions per week, '
            f'last 52 weeks</text>')
    for i, n in enumerate(weeks):
        bh = max(3.0, 84 * (n / peak) ** 0.6)
        body += (f'<rect x="{32 + i * step:.1f}" y="{132 - bh / 2:.1f}" '
                 f'width="{step * 0.58:.1f}" height="{bh:.1f}" rx="{step * 0.29:.1f}" '
                 f'fill="{C["accent"]}" opacity="{0.35 + 0.6 * n / peak:.2f}"/>')
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
                 f'fill="{C["ink"]}">{fmt(value)}</text>'
                 f'<text x="{x}" y="236" font-size="12" fill="{C["mute"]}">{label}</text>')
    return svg(W, H, body, f"Contribution rhythm for {USER}")


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
