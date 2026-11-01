#!/usr/bin/env python3
"""Refresh the profile from public GitHub data only.

This script intentionally makes unauthenticated requests to the public GitHub
REST API. Private/locked repositories are therefore never returned or shown.
"""
from __future__ import annotations

import datetime as dt
import html
import json
import os
import pathlib
import urllib.error
import urllib.request

USERNAME = "Adarsh-Singh-Chauhan"
PROFILE_REPO = f"{USERNAME}/{USERNAME}"
ROOT = pathlib.Path(__file__).resolve().parents[1]
README = ROOT / "README.md"
DIST = ROOT / "dist"
HEADERS = {
    "Accept": "application/vnd.github+json",
    "User-Agent": "Adarsh-GitHub-Profile-Sync",
    "X-GitHub-Api-Version": "2022-11-28",
}


def api_json(url: str):
    request = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(request, timeout=25) as response:
        return json.loads(response.read().decode("utf-8"))


def safe_text(value: str | None, limit: int = 88) -> str:
    text = " ".join((value or "").split())
    if len(text) > limit:
        text = text[: limit - 1].rstrip() + "…"
    return text or "Project repository"


def replace_section(content: str, start: str, end: str, replacement: str) -> str:
    a = content.find(start)
    b = content.find(end)
    if a < 0 or b < 0 or b < a:
        raise RuntimeError(f"README markers missing or misordered: {start}")
    return content[: a + len(start)] + "\n" + replacement.rstrip() + "\n" + content[b:]


def date_label(value: str | None) -> str:
    if not value:
        return "date unavailable"
    try:
        return dt.datetime.fromisoformat(value.replace("Z", "+00:00")).strftime("%d %b %Y")
    except ValueError:
        return value[:10]


def event_description(event: dict) -> str:
    kind = event.get("type", "Activity")
    payload = event.get("payload") or {}
    actions = {
        "PushEvent": f"Pushed {payload.get('size', 1)} commit(s) to",
        "CreateEvent": f"Created {payload.get('ref_type', 'a ref')} in",
        "PullRequestEvent": f"{payload.get('action', 'updated').capitalize()} a pull request in",
        "IssuesEvent": f"{payload.get('action', 'updated').capitalize()} an issue in",
        "ReleaseEvent": f"Published a release in",
        "WatchEvent": "Starred",
        "ForkEvent": "Forked",
    }
    return actions.get(kind, kind.replace("Event", " event"))


def make_stats_svg(public_repos: int, stars: int, forks: int, followers: int) -> str:
    cards = [
        ("PUBLIC REPOS", public_repos, "#22d3ee"),
        ("STARS EARNED", stars, "#f472b6"),
        ("COMMUNITY FORKS", forks, "#a78bfa"),
        ("FOLLOWERS", followers, "#4ade80"),
    ]
    blocks = []
    for i, (label, value, accent) in enumerate(cards):
        x = 10 + (i % 2) * 244
        y = 10 + (i // 2) * 118
        blocks.append(
            f'<g transform="translate({x},{y})"><rect width="232" height="106" rx="13" fill="#0b1222" stroke="{accent}" stroke-opacity=".75" stroke-width="1.5"/>'
            f'<circle cx="18" cy="22" r="4" fill="{accent}"/>'
            f'<text x="31" y="26" fill="#9fb5cf" font-family="Arial,sans-serif" font-size="10" letter-spacing=".8">{html.escape(label)}</text>'
            f'<text x="18" y="76" fill="#f8fafc" font-family="Arial,sans-serif" font-size="38" font-weight="800">{value:,}</text>'
            f'<path d="M18 89H214" stroke="{accent}" stroke-opacity=".4" stroke-width="2"/></g>'
        )
    return (
        '<svg xmlns="http://www.w3.org/2000/svg" width="500" height="234" viewBox="0 0 500 234">'
        '<rect width="500" height="234" rx="18" fill="#070b16"/>'
        + "".join(blocks)
        + "</svg>"
    )

def make_languages_svg(language_bytes: dict[str, int]) -> str:
    palette = {
        "TypeScript": "#3178c6", "JavaScript": "#f1e05a", "Python": "#3572A5",
        "Java": "#b07219", "HTML": "#e34c26", "CSS": "#563d7c",
        "C++": "#f34b7d", "C": "#555555", "C#": "#178600",
        "Go": "#00ADD8", "Rust": "#dea584", "PHP": "#4F5D95",
        "Jupyter Notebook": "#DA5B0B", "Shell": "#89e051", "Dart": "#00B4AB",
    }
    total = sum(language_bytes.values()) or 1
    ranked = sorted(language_bytes.items(), key=lambda item: item[1], reverse=True)[:8]
    x, y, bar_width, bar_height = 18, 68, 464, 14
    bars = []
    cursor = x
    for name, amount in ranked:
        width = max(3, bar_width * amount / total)
        color = palette.get(name, "#8b9bb4")
        bars.append(f'<rect x="{cursor:.1f}" y="{y}" width="{width:.1f}" height="{bar_height}" fill="{color}"/>')
        cursor += width
    legend = []
    for i, (name, amount) in enumerate(ranked):
        col, row = i % 2, i // 2
        lx, ly = 22 + col * 244, 111 + row * 24
        pct = amount / total * 100
        color = palette.get(name, "#8b9bb4")
        legend.append(
            f'<circle cx="{lx}" cy="{ly - 4}" r="4" fill="{color}"/>'
            f'<text x="{lx + 11}" y="{ly}" fill="#dbeafe" font-family="Arial,sans-serif" font-size="11">{html.escape(name)} · {pct:.1f}%</text>'
        )
    if not ranked:
        legend = ['<text x="22" y="112" fill="#94a3b8" font-family="Arial,sans-serif" font-size="11">Language data will appear after public repository data is available.</text>']
    return (
        '<svg xmlns="http://www.w3.org/2000/svg" width="500" height="220" viewBox="0 0 500 220">'
        '<rect width="500" height="220" rx="16" fill="#070b16" stroke="#26364e"/>'
        '<text x="20" y="30" fill="#f8fafc" font-family="Arial,sans-serif" font-size="15" font-weight="700">MOST USED LANGUAGES</text>'
        '<text x="20" y="49" fill="#8fa8c3" font-family="Arial,sans-serif" font-size="10">Public repositories · source byte count</text>'
        f'<rect x="{x}" y="{y}" width="{bar_width}" height="{bar_height}" rx="7" fill="#1b2940"/>'
        + "".join(bars)
        + "".join(legend)
        + "</svg>"
    )

def make_activity_svg(events: list[dict]) -> str:
    selected = events[:5]
    pieces = []
    for i, event in enumerate(selected):
        y = 72 + i * 43
        repo_name = (event.get("repo") or {}).get("name", "Public GitHub activity")
        label = event_description(event)
        pieces.append(
            f'<circle cx="30" cy="{y - 4}" r="6" fill="{["#22d3ee", "#f472b6", "#a78bfa", "#4ade80", "#fbbf24"][i]}"/>'
            f'<text x="50" y="{y}" fill="#e2e8f0" font-family="Arial,sans-serif" font-size="13">{html.escape(safe_text(label + " " + repo_name, 82))}</text>'
            f'<text x="50" y="{y + 17}" fill="#7890aa" font-family="Arial,sans-serif" font-size="10">{date_label(event.get("created_at"))}</text>'
        )
    if not pieces:
        pieces.append('<text x="30" y="85" fill="#9fb5cf" font-family="Arial,sans-serif" font-size="14">No recent public events were returned by GitHub.</text>')
    return (
        '<svg xmlns="http://www.w3.org/2000/svg" width="1000" height="300" viewBox="0 0 1000 300">'
        '<rect width="1000" height="300" rx="18" fill="#070b16" stroke="#26364e"/>'
        '<text x="28" y="38" fill="#f8fafc" font-family="Arial,sans-serif" font-size="19" font-weight="700">LATEST PUBLIC ACTIVITY</text>'
        '<text x="28" y="56" fill="#8fa8c3" font-family="Arial,sans-serif" font-size="11">Recent public GitHub events · private repository activity is not queried</text>'
        '<path d="M30 74V260" stroke="#354967" stroke-width="2"/>'
        + "".join(pieces)
        + "</svg>"
    )


def main() -> None:
    DIST.mkdir(parents=True, exist_ok=True)

    # Unauthenticated public endpoints deliberately exclude private/locked repositories.
    user = api_json(f"https://api.github.com/users/{USERNAME}")
    raw_repos = api_json(f"https://api.github.com/users/{USERNAME}/repos?sort=pushed&per_page=100&type=owner")
    repos = [
        r for r in raw_repos
        if r.get("private") is False
        and not r.get("fork")
        and not r.get("archived")
        and r.get("full_name") != PROFILE_REPO
    ]
    repos.sort(key=lambda r: r.get("pushed_at") or r.get("updated_at") or "", reverse=True)

    public_count = int(user.get("public_repos", len(repos)))
    total_stars = sum(int(r.get("stargazers_count", 0)) for r in raw_repos if r.get("private") is False)
    total_forks = sum(int(r.get("forks_count", 0)) for r in raw_repos if r.get("private") is False)
    followers = int(user.get("followers", 0))

    recent_rows = []
    for r in repos[:8]:
        name = html.escape(r.get("name", "repository"))
        url = r.get("html_url", "#")
        description = safe_text(r.get("description"), 94).replace("|", "/")
        language = r.get("language") or "—"
        stars = int(r.get("stargazers_count", 0))
        pushed = date_label(r.get("pushed_at") or r.get("updated_at"))
        recent_rows.append(f"| [{name}]({url}) | {html.escape(description)} | {html.escape(language)} | ★ {stars} | {pushed} |")
    if not recent_rows:
        recent_rows = ["| No public repositories found | — | — | — | — |"]
    repo_markdown = (
        "| Repository | Description | Primary language | Stars | Last pushed |\n"
        "|---|---|---:|---:|---:|\n"
        + "\n".join(recent_rows)
        + "\n\n<sub>Automatically refreshed every 6 hours from GitHub's public repository API. Private/locked repositories are not queried or displayed.</sub>"
    )

    try:
        events = api_json(f"https://api.github.com/users/{USERNAME}/events/public?per_page=100")
        events = [e for e in events if e.get("type") in {
            "PushEvent", "CreateEvent", "PullRequestEvent", "IssuesEvent", "ReleaseEvent", "WatchEvent", "ForkEvent"
        }][:5]
    except Exception:
        events = []

    activity_rows = []
    for e in events:
        repo_name = (e.get("repo") or {}).get("name", "public repository")
        desc = event_description(e)
        activity_rows.append(f"- **{date_label(e.get('created_at'))}** — {desc} [{repo_name}](https://github.com/{repo_name})")
    if not activity_rows:
        activity_rows = ["- No recent public activity was returned by GitHub's public Events API."]
    activity_markdown = "\n".join(activity_rows) + "\n\n<sub>Public events only. Private repository activity is intentionally omitted.</sub>"

    # Aggregate real language byte counts from the most recently pushed public repositories.
    language_bytes: dict[str, int] = {}
    for repo in [r for r in repos if r.get("language")][:24]:
        try:
            language_map = api_json(repo["languages_url"])
            for language, amount in language_map.items():
                language_bytes[language] = language_bytes.get(language, 0) + int(amount)
        except Exception:
            continue

    readme = README.read_text(encoding="utf-8")
    readme = replace_section(
        readme,
        "<!-- PROFILE:RECENT-REPOS:START -->",
        "<!-- PROFILE:RECENT-REPOS:END -->",
        repo_markdown,
    )
    readme = replace_section(
        readme,
        "<!-- PROFILE:PUBLIC-ACTIVITY:START -->",
        "<!-- PROFILE:PUBLIC-ACTIVITY:END -->",
        activity_markdown,
    )
    README.write_text(readme, encoding="utf-8")

    (DIST / "profile-stats.svg").write_text(
        make_stats_svg(public_count, total_stars, total_forks, followers), encoding="utf-8"
    )
    (DIST / "languages.svg").write_text(make_languages_svg(language_bytes), encoding="utf-8")
    (DIST / "public-activity.svg").write_text(make_activity_svg(events), encoding="utf-8")
    print(f"Refreshed public profile data: {len(repos)} public repos, {len(events)} recent events.")


if __name__ == "__main__":
    main()
