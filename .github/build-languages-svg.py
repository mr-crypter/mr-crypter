"""Measure language usage across the repos that actually matter, then render
assets/languages.svg.

The lowlighter/metrics card can only see repositories mr-crypter owns, which
hides all the C++ (it lives entirely in the private 0xMidax org repos).
Widening metrics' own scope does not work: it caps the repo fetch at 100
BEFORE applying skip patterns, so dapplooker's ~73 repos crowd everything out.

So this measures the scope directly and draws its own bar:

    mr-crypter/*  +  0xMidax/*  +  dapplooker/loky-backend

Runs daily in generate-stats.yml. Needs GITHUB_TOKEN with repo scope to see
the private org repos.

    GITHUB_TOKEN=... python .github/build-languages-svg.py
"""

import json
import os
import sys
import urllib.error
import urllib.request

SCOPE_USERS = ["mr-crypter"]  # every non-fork repo owned by these users
SCOPE_ORGS = ["0xMidax"]  # every non-fork repo in these orgs
SCOPE_REPOS = ["dapplooker/loky-backend"]  # individually named repos

# Notebooks are mostly serialized output rather than authored code, and they
# were 32% of raw bytes, which swamped everything else.
IGNORED = {"Jupyter Notebook"}
LIMIT = 8

API = "https://api.github.com"
TOKEN = os.environ.get("GITHUB_TOKEN", "")

# GitHub linguist colours. Anything unlisted falls back to grey.
COLOURS = {
    "TypeScript": "#3178c6", "C++": "#f34b7d", "Python": "#3572A5",
    "JavaScript": "#f1e05a", "Shell": "#89e051", "CMake": "#DA3434",
    "PLpgSQL": "#336790", "CSS": "#663399", "HTML": "#e34c26",
    "HCL": "#844FBA", "Dockerfile": "#384d54", "Go": "#00ADD8",
    "Makefile": "#427819", "Solidity": "#AA6746", "Rust": "#dea584",
    "C": "#555555", "Java": "#b07219", "Ruby": "#701516", "SCSS": "#c6538c",
    "Vue": "#41b883", "Svelte": "#ff3e00", "Kotlin": "#A97BFF",
    "Swift": "#F05138", "PHP": "#4F5D95", "Lua": "#000080",
    "PowerShell": "#012456", "Batchfile": "#C1F12E", "Nix": "#7e7eff",
}
FALLBACK = "#8b949e"

WIDTH, PAD, BAR_Y, BAR_H = 960, 20, 46, 10
BAR_W = WIDTH - 2 * PAD
PER_ROW, ROW_H = 4, 26
TEXT, TITLE = "#9CA3AF", "#58a6ff"


def api(path):
    """GET an API path, following pagination."""
    results, url = [], f"{API}{path}"
    while url:
        req = urllib.request.Request(url, headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {TOKEN}",
            "User-Agent": "mr-crypter-readme",
        })
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                results.append(json.load(resp))
                link = resp.headers.get("Link", "")
        except urllib.error.HTTPError as exc:
            # A repo we cannot see is not fatal; the scope is best-effort.
            print(f"  skip {url.replace(API, '')}: HTTP {exc.code}", file=sys.stderr)
            return results
        url = ""
        for part in link.split(","):
            if 'rel="next"' in part:
                url = part.split(";")[0].strip().strip("<>")
    return results


def collect_repos():
    """Repos in scope, private ones included.

    Listed via /user/repos rather than /users/<name>/repos: the latter only
    returns public repos, which silently dropped ~6 private ones.
    """
    wanted = {name.lower() for name in SCOPE_USERS + SCOPE_ORGS}
    repos = set(SCOPE_REPOS)
    for page in api("/user/repos?per_page=100&affiliation=owner,organization_member"):
        for r in page:
            if not r["fork"] and r["owner"]["login"].lower() in wanted:
                repos.add(r["full_name"])
    return sorted(repos)


def measure(repos):
    totals = {}
    for repo in repos:
        for page in api(f"/repos/{repo}/languages"):
            for name, size in page.items():
                if name not in IGNORED:
                    totals[name] = totals.get(name, 0) + size
    return totals


def render(totals):
    ranked = sorted(totals.items(), key=lambda kv: kv[1], reverse=True)[:LIMIT]
    if not ranked:
        raise SystemExit("no language data collected; refusing to write an empty chart")

    # Percentages are of the languages actually shown, so the legend sums to 100.
    total = sum(size for _, size in ranked)
    rows = (len(ranked) + PER_ROW - 1) // PER_ROW
    height = BAR_Y + BAR_H + 18 + rows * ROW_H

    out = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{WIDTH}" height="{height}" '
        f'viewBox="0 0 {WIDTH} {height}" font-family="Segoe UI, Ubuntu, Helvetica, sans-serif">',
        f'<text x="{PAD}" y="28" fill="{TITLE}" font-size="15" font-weight="600">Most used languages</text>',
        f'<clipPath id="bar"><rect x="{PAD}" y="{BAR_Y}" width="{BAR_W}" height="{BAR_H}" rx="{BAR_H / 2}"/></clipPath>',
        '<g clip-path="url(#bar)">',
    ]
    x = PAD
    for name, size in ranked:
        w = BAR_W * size / total
        out.append(f'<rect x="{x:.2f}" y="{BAR_Y}" width="{w:.2f}" height="{BAR_H}" '
                   f'fill="{COLOURS.get(name, FALLBACK)}"/>')
        x += w
    out.append("</g>")

    col_w = BAR_W / PER_ROW
    for i, (name, size) in enumerate(ranked):
        cx = PAD + (i % PER_ROW) * col_w
        cy = BAR_Y + BAR_H + 32 + (i // PER_ROW) * ROW_H
        out.append(f'<circle cx="{cx + 5:.2f}" cy="{cy - 4:.2f}" r="5" '
                   f'fill="{COLOURS.get(name, FALLBACK)}"/>')
        out.append(f'<text x="{cx + 18:.2f}" y="{cy:.2f}" fill="{TEXT}" font-size="13">'
                   f"{name} {100 * size / total:.2f}%</text>")
    out.append("</svg>")

    with open("assets/languages.svg", "w", encoding="utf-8", newline="\n") as fh:
        fh.write("\n".join(out) + "\n")
    for name, size in ranked:
        print(f"  {name:<14} {size:>10,}  {100 * size / total:5.2f}%")


if __name__ == "__main__":
    if not TOKEN:
        raise SystemExit("GITHUB_TOKEN is required to read the private org repos")
    found = collect_repos()
    print(f"measuring {len(found)} repos")
    render(measure(found))
