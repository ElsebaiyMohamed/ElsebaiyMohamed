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


def activity():
    """Last-12-month contribution counts (GraphQL needs a token)."""
    if not TOKEN:
        return {}
    query = ("query($login:String!){user(login:$login){contributionsCollection{"
             "totalCommitContributions totalPullRequestContributions "
             "totalIssueContributions}}}")
    res = _request("https://api.github.com/graphql",
                   {"query": query, "variables": {"login": USER}})
    if "errors" in res:
        raise RuntimeError(res["errors"])
    c = res["data"]["user"]["contributionsCollection"]
    return {"Commits": c["totalCommitContributions"],
            "Pull requests": c["totalPullRequestContributions"],
            "Issues": c["totalIssueContributions"]}


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
    shares = [(n, b * 100 / grand) for n, b in ranked[:5]]
    other = sum(b for _, b in ranked[5:])
    if other:
        shares.append(("Other", other * 100 / grand))
    return shares


def fmt(n):
    return "–" if n is None else f"{n:,}"


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


def stats(owned, act, langs):
    W, H = 820, 250
    stars = sum(r["stargazers_count"] for r in owned)
    metrics = [("Commits", act.get("Commits")), ("Pull requests", act.get("Pull requests")),
               ("Issues", act.get("Issues")), ("Stars earned", stars),
               ("Public repos", len(owned))]

    body = (f'<text x="32" y="48" font-size="22" font-weight="700" fill="{C["ink"]}">'
            f'{escape(USER)}</text>'
            f'<text x="32" y="70" font-size="13" fill="{C["mute"]}">Commits, pull requests '
            f'and issues cover the last 12 months</text>')
    body += wave(USER, 520, 24, 268, 44)
    for i, (label, value) in enumerate(metrics):
        x = 32 + i * 152
        body += (f'<text x="{x}" y="130" font-size="34" font-weight="700" '
                 f'fill="{C["ink"]}">{fmt(value)}</text>'
                 f'<text x="{x}" y="152" font-size="12" fill="{C["mute"]}">{label}</text>')

    total_w, x = W - 64, 32.0
    segs = ""
    for name, pct in langs:
        w = total_w * pct / 100
        segs += (f'<rect x="{x:.1f}" y="186" width="{w:.1f}" height="10" '
                 f'fill="{lang_color(name)}"/>')
        x += w
    body += (f'<clipPath id="bar"><rect x="32" y="186" width="{total_w}" height="10" '
             f'rx="5"/></clipPath><g clip-path="url(#bar)">{segs}</g>')
    for i, (name, pct) in enumerate(langs):
        lx = 32 + i * 126
        body += (f'<circle cx="{lx + 5}" cy="221" r="5" fill="{lang_color(name)}"/>'
                 f'<text x="{lx + 16}" y="225" font-size="12" fill="{C["ink"]}">'
                 f'{escape(name)} {pct:.0f}%</text>')
    return svg(W, H, body, f"GitHub activity for {USER}")


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
    write("stats.svg", stats(owned, activity(), language_shares(owned)))


if __name__ == "__main__":
    main()
