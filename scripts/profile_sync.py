#!/usr/bin/env python3
"""Refresh a GitHub profile using public repositories and public events only.

The activity game card is built from commit records authored by the profile owner and approved public team activity
in public repositories. Private repository contents and private contribution data
are never requested.
"""
from __future__ import annotations

import concurrent.futures
import datetime as dt
import html
import json
import os
import pathlib
import urllib.error
import urllib.parse
import urllib.request
from zoneinfo import ZoneInfo

USERNAME = "Adarsh-Singh-Chauhan"
PROFILE_REPO = f"{USERNAME}/{USERNAME}"
COLLAB_REPOSITORIES = ("Ansh-Dubey-05/Ansh-Portfolio",)
ROOT = pathlib.Path(__file__).resolve().parents[1]
README = ROOT / "README.md"
DIST = ROOT / "dist"
IST = ZoneInfo("Asia/Kolkata")
TOKEN = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
HEADERS = {
    "Accept": "application/vnd.github+json",
    "User-Agent": "Adarsh-GitHub-Profile-Sync",
    "X-GitHub-Api-Version": "2022-11-28",
}
if TOKEN:
    HEADERS["Authorization"] = f"Bearer {TOKEN}"


def api_json(url: str):
    request = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.loads(response.read().decode("utf-8"))


def safe_text(value: str | None, limit: int = 88) -> str:
    text = " ".join((value or "").split())
    if len(text) > limit:
        text = text[: limit - 1].rstrip() + "…"
    return text or "Project repository"


def date_label(value: str | None) -> str:
    if not value:
        return "date unavailable"
    try:
        value_dt = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
        return value_dt.astimezone(IST).strftime("%d %b %Y · %I:%M %p IST")
    except ValueError:
        return value[:10]


def iso_utc(value: dt.datetime) -> str:
    return value.astimezone(dt.timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def list_public_repositories() -> list[dict]:
    public: list[dict] = []
    page = 1
    while True:
        url = (
            f"https://api.github.com/users/{USERNAME}/repos"
            f"?type=owner&sort=pushed&per_page=100&page={page}"
        )
        batch = api_json(url)
        if not isinstance(batch, list):
            raise RuntimeError("GitHub repositories endpoint returned an unexpected response.")
        public.extend(repo for repo in batch if repo.get("private") is False)
        if len(batch) < 100:
            break
        page += 1
    return public


def commits_for_repo(repo: dict, since: str) -> list[dict]:
    """Get commits attributed by GitHub to USERNAME in one public repository."""
    owner = repo.get("owner", {}).get("login", USERNAME)
    name = repo.get("name")
    if not name:
        return []
    encoded_since = urllib.parse.quote(since, safe=":")
    commits: list[dict] = []
    page = 1
    while True:
        url = (
            f"https://api.github.com/repos/{owner}/{name}/commits"
            f"?author={USERNAME}&since={encoded_since}&per_page=100&page={page}"
        )
        try:
            batch = api_json(url)
        except urllib.error.HTTPError as exc:
            # An empty repository or an inaccessible/deleted public repo should
            # not fail the entire profile refresh.
            if exc.code in (404, 409, 422):
                return commits
            raise
        if not isinstance(batch, list):
            return commits
        for commit in batch:
            commit["_repo_full_name"] = f"{owner}/{name}"
        commits.extend(batch)
        if len(batch) < 100:
            break
        page += 1
    return commits


def collect_public_commits(repositories: list[dict], since: str) -> list[dict]:
    now = dt.datetime.now(dt.timezone.utc)
    active = []
    for repo in repositories:
        pushed = repo.get("pushed_at")
        if not pushed:
            continue
        try:
            pushed_at = dt.datetime.fromisoformat(pushed.replace("Z", "+00:00"))
            if pushed_at >= now - dt.timedelta(days=92):
                active.append(repo)
        except ValueError:
            continue

    unique: dict[str, dict] = {}
    errors = 0
    with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:
        futures = {
            pool.submit(commits_for_repo, repo, since): repo
            for repo in active
        }
        for future in concurrent.futures.as_completed(futures):
            try:
                for commit in future.result():
                    sha = commit.get("sha")
                    if sha:
                        unique[sha] = commit
            except Exception as exc:
                errors += 1
                print(f"Warning: could not inspect {futures[future].get('full_name')}: {exc}")

    if errors:
        print(f"Warning: commit history could not be read for {errors} public repositories.")
    return list(unique.values())


def commit_day(commit: dict) -> dt.date | None:
    try:
        committed = commit["commit"]["author"]["date"]
        return dt.datetime.fromisoformat(committed.replace("Z", "+00:00")).astimezone(IST).date()
    except (KeyError, TypeError, ValueError):
        return None


def group_public_events(events: list[dict]) -> list[dict]:
    """Collapse repeated same-day push events for the same repository."""
    grouped: dict[tuple, dict] = {}
    allowed = {
        "PushEvent", "CreateEvent", "PullRequestEvent", "IssuesEvent",
        "ReleaseEvent", "WatchEvent", "ForkEvent",
    }
    for event in events:
        kind = event.get("type")
        if kind not in allowed:
            continue
        repo_name = (event.get("repo") or {}).get("name", "public repository")
        created = event.get("created_at")
        if not created:
            continue
        try:
            date_key = dt.datetime.fromisoformat(created.replace("Z", "+00:00")).astimezone(IST).date().isoformat()
        except ValueError:
            date_key = created[:10]
        key = (kind, repo_name, date_key)
        if key not in grouped:
            grouped[key] = {
                "type": kind, "repo": repo_name, "date": date_key,
                "count": 0, "latest": created, "action": (event.get("payload") or {}).get("action"),
            }
        item = grouped[key]
        item["count"] += int((event.get("payload") or {}).get("size", 1)) if kind == "PushEvent" else 1
        if created > item["latest"]:
            item["latest"] = created
    return sorted(grouped.values(), key=lambda item: item["latest"], reverse=True)[:7]


def event_label(item: dict) -> str:
    kind = item["type"]
    repo = item["repo"].split("/")[-1]
    count = item.get("count", 1)
    if kind == "PushEvent":
        return f"Pushed {count} commit(s) to {repo}"
    if kind == "CreateEvent":
        return f"Created a branch or tag in {repo}"
    if kind == "PullRequestEvent":
        return f"{(item.get('action') or 'Updated').capitalize()} a pull request in {repo}"
    if kind == "IssuesEvent":
        return f"{(item.get('action') or 'Updated').capitalize()} an issue in {repo}"
    if kind == "ReleaseEvent":
        return f"Published a release in {repo}"
    if kind == "WatchEvent":
        return f"Starred {repo}"
    if kind == "ForkEvent":
        return f"Forked {repo}"
    return f"Activity in {repo}"


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
        + "".join(bars) + "".join(legend) + "</svg>"
    )


def group_recent_commits(commits: list[dict], limit: int = 7) -> list[dict]:
    grouped: dict[tuple, dict] = {}
    for commit in commits:
        day = commit_day(commit)
        repo_name = commit.get("_repo_full_name")
        if not day or not repo_name:
            continue
        key = (repo_name, day.isoformat())
        if key not in grouped:
            message = ((commit.get("commit") or {}).get("message") or "").splitlines()[0]
            grouped[key] = {
                "repo": repo_name, "date": day.isoformat(), "count": 0,
                "message": safe_text(message, 74), "latest": day.isoformat(),
            }
        grouped[key]["count"] += 1
    return sorted(
        grouped.values(),
        key=lambda item: (item["date"], item["count"]),
        reverse=True,
    )[:limit]


def make_activity_svg(items: list[dict], updated_at: str) -> str:
    selected = items[:7]
    height = 112 + max(1, len(selected)) * 58
    rows = []
    accents = ["#27e7ff", "#ff4fb7", "#b58cff", "#4ade80", "#f5c451", "#60a5fa", "#fb7185"]
    pill_x, pill_width = 820, 120
    for i, item in enumerate(selected):
        y = 82 + i * 58
        accent = accents[i % len(accents)]
        repo_name = item["repo"]
        short_name = repo_name.split("/")[-1]
        count = max(0, int(item.get("count", 1)))
        display_count = f"{count:,}"
        message = safe_text(item.get("message"), 68)
        date = item["date"]
        label = f"{display_count} COMMIT{'S' if count != 1 else ''}"
        font_size = 10 if len(label) > 13 else 11
        rows.append(
            f'<g transform="translate(24,{y})">'
            f'<rect width="952" height="48" rx="10" fill="#0d1729" stroke="#344762" stroke-opacity=".72"/>'
            f'<rect width="4" height="48" rx="2" fill="{accent}"/>'
            f'<circle cx="24" cy="24" r="8" fill="{accent}" fill-opacity=".13" stroke="{accent}" stroke-opacity=".85"/>'
            f'<circle cx="24" cy="24" r="3" fill="{accent}"/>'
            f'<text x="44" y="20" fill="#f4f8ff" font-family="Arial,sans-serif" font-size="13" font-weight="700">{html.escape(safe_text(short_name, 32))}</text>'
            f'<text x="44" y="36" fill="#849bb7" font-family="Arial,sans-serif" font-size="9.2">{html.escape(message)}</text>'
            f'<text x="690" y="20" fill="#7c91ad" font-family="Arial,sans-serif" font-size="9">{html.escape(date)} · IST</text>'
            f'<rect x="{pill_x}" y="8" width="{pill_width}" height="32" rx="9" fill="{accent}" fill-opacity=".12" stroke="{accent}" stroke-opacity=".7"/>'
            f'<text x="{pill_x + pill_width / 2}" y="28" text-anchor="middle" dominant-baseline="middle" fill="{accent}" font-family="Arial,sans-serif" font-size="{font_size}" font-weight="800" textLength="{pill_width - 12}" lengthAdjust="spacingAndGlyphs">{html.escape(label)}</text>'
            f'</g>'
        )
    if not rows:
        rows.append(
            '<text x="34" y="115" fill="#9fb5cf" font-family="Arial,sans-serif" font-size="14">'
            'No public commits found in the 90-day activity window.</text>'
        )
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="1000" height="{height}" viewBox="0 0 1000 {height}">'
        '<defs>'
        '<linearGradient id="logEdge" x1="0" x2="1"><stop stop-color="#27e7ff"/><stop offset=".5" stop-color="#9b72ff"/><stop offset="1" stop-color="#ff4fb7"/></linearGradient>'
        '<pattern id="logGrid" width="28" height="28" patternUnits="userSpaceOnUse"><path d="M28 0H0V28" fill="none" stroke="#7187a5" stroke-opacity=".06"/></pattern>'
        '<filter id="logGlow"><feGaussianBlur stdDeviation="3" result="b"/><feMerge><feMergeNode in="b"/><feMergeNode in="SourceGraphic"/></feMerge></filter>'
        '</defs>'
        f'<rect width="1000" height="{height}" rx="20" fill="#070b16" stroke="#344762" stroke-width="1.2"/>'
        f'<rect width="1000" height="{height}" rx="20" fill="url(#logGrid)"/>'
        '<path d="M20 63H980" stroke="url(#logEdge)" stroke-width="2" opacity=".9" filter="url(#logGlow)"/>'
        '<rect x="24" y="19" width="5" height="24" rx="2" fill="#27e7ff"/>'
        '<text x="42" y="34" fill="#f5f8ff" font-family="Arial,sans-serif" font-size="19" font-weight="800" letter-spacing=".7">COMBAT LOG // LATEST PUBLIC COMMITS</text>'
        f'<text x="976" y="34" text-anchor="end" fill="#4ade80" font-family="Arial,sans-serif" font-size="9.5" font-weight="700">● LIVE SYNC</text>'
        f'<text x="25" y="53" fill="#8299b7" font-family="Arial,sans-serif" font-size="10">PUBLIC REPOSITORIES · GROUPED BY PROJECT + INDIA DATE · {html.escape(updated_at)}</text>'
        + "".join(rows)
        + f'<text x="25" y="{height - 14}" fill="#637b9b" font-family="Arial,sans-serif" font-size="9">SOURCE: GITHUB COMMITS API · PRIVATE REPOSITORIES EXCLUDED</text>'
        + f'<text x="975" y="{height - 14}" text-anchor="end" fill="#27e7ff" font-family="Arial,sans-serif" font-size="9">ASC / ENGINEERING FEED</text>'
        + "</svg>"
    )

def make_daily_quest_svg(
    today: dt.date,
    daily_counts: dict[dt.date, int],
    public_repos: int,
    stars: int,
    updated_at: str,
    portfolio_stats: dict | None,
) -> str:
    today_count = daily_counts.get(today, 0)
    week = [today - dt.timedelta(days=i) for i in range(6, -1, -1)]
    weekly_total = sum(daily_counts.get(day, 0) for day in week)
    xp = weekly_total * 25
    level = xp // 500 + 1
    current_xp = xp % 500
    goal = 5
    goal_percent = min(100, int(today_count / goal * 100))
    streak_end = today if today_count else today - dt.timedelta(days=1)
    streak = 0
    check = streak_end
    while daily_counts.get(check, 0) > 0 and streak < 90:
        streak += 1
        check -= dt.timedelta(days=1)

    totals = (portfolio_stats or {}).get("total") or {}
    unique_visitors = totals.get("uv")
    page_views = totals.get("pv")
    unique_value = f"{unique_visitors:,}" if isinstance(unique_visitors, int) else "SYNC PENDING"
    page_views_value = f"{page_views:,}" if isinstance(page_views, int) else "SYNC PENDING"

    cards = [
        ("TODAY'S COMMITS", f"{today_count:,}", "#27e7ff", "PUBLIC COMMIT RECORDS", "01"),
        ("PUBLIC REPOSITORIES", f"{public_repos:,}", "#ff4fb7", "ACCOUNT-WIDE COUNT", "02"),
        ("UNIQUE VISITORS · 30D", unique_value, "#f5c451", "VERCEL WEB ANALYTICS", "03"),
        ("PAGE VIEWS · 30D", page_views_value, "#60a5fa", "VERCEL WEB ANALYTICS", "04"),
        ("CURRENT STREAK", f"{streak} DAYS", "#4ade80", "CONSECUTIVE ACTIVE DAYS", "05"),
        (f"LEVEL {level} · WEEKLY XP", f"{xp:,}", "#b58cff", "25 XP / PUBLIC COMMIT", "06"),
    ]

    blocks = []
    card_width = 360
    x_positions = [28, 420, 812]
    y_positions = [91, 184]
    for i, (label, value, accent, subtitle, number) in enumerate(cards):
        x = x_positions[i % 3]
        y = y_positions[i // 3]
        value_size = 18 if len(value) > 10 else 23
        blocks.append(
            f'<g transform="translate({x},{y})">'
            f'<rect width="{card_width}" height="78" rx="14" fill="#0c1729" stroke="{accent}" stroke-opacity=".78" stroke-width="1.25"/>'
            f'<path d="M14 1H{card_width - 14}" stroke="{accent}" stroke-width="2" opacity=".82"/>'
            f'<text x="17" y="23" fill="#9bb0ca" font-family="Arial,sans-serif" font-size="10" font-weight="700" letter-spacing=".7">{html.escape(label)}</text>'
            f'<text x="17" y="53" fill="#f7fbff" font-family="Arial,sans-serif" font-size="{value_size}" font-weight="900">{html.escape(value)}</text>'
            f'<text x="{card_width - 17}" y="23" text-anchor="end" fill="{accent}" opacity=".8" font-family="Arial,sans-serif" font-size="8.5" font-weight="700">{number}</text>'
            f'<text x="{card_width - 17}" y="57" text-anchor="end" fill="{accent}" font-family="Arial,sans-serif" font-size="8.5" font-weight="700">{html.escape(subtitle)}</text>'
            f'</g>'
        )

    chart_x = 78
    chart_y = 365
    chart_h = 104
    max_value = max([daily_counts.get(day, 0) for day in week] + [1])
    bar_w = 82
    gap = 67
    bars = []
    for i, day in enumerate(week):
        count = daily_counts.get(day, 0)
        h = max(4, chart_h * count / max_value) if count else 4
        x = chart_x + 8 + i * (bar_w + gap)
        y = chart_y + chart_h - h
        is_today = day == today
        accent = "#27d9f5" if is_today else "#8b72ff"
        value_size = 11 if count < 1000 else 9.5
        bars.append(
            f'<rect x="{x}" y="{y:.1f}" width="{bar_w}" height="{h:.1f}" rx="8" fill="{accent}" opacity=".94"/>'
            f'<rect x="{x}" y="{y:.1f}" width="{bar_w}" height="3" rx="2" fill="#ffffff" opacity=".32"/>'
            f'<text x="{x + bar_w / 2}" y="{y - 10:.1f}" text-anchor="middle" fill="#f1f6ff" font-family="Arial,sans-serif" font-size="{value_size}" font-weight="800">{count:,}</text>'
            f'<text x="{x + bar_w / 2}" y="{chart_y + chart_h + 22}" text-anchor="middle" fill="{accent if is_today else "#9badc6"}" font-family="Arial,sans-serif" font-size="10" font-weight="700">{day.strftime("%a").upper()}</text>'
        )

    progress_width = 1044 * goal_percent / 100
    visitor_status = "VERCEL PORTFOLIO · WEB ANALYTICS · LAST 30 DAYS"
    if not isinstance(unique_visitors, int) or not isinstance(page_views, int):
        visitor_status += " · ENABLE ANALYTICS + ADD SERVER TOKEN TO SYNC"

    return (
        '<svg xmlns="http://www.w3.org/2000/svg" width="1200" height="570" viewBox="0 0 1200 570" role="img" aria-labelledby="questTitle questDesc">'
        '<title id="questTitle">ASC Developer Quest and portfolio traffic</title>'
        '<desc id="questDesc">Developer activity dashboard with public commits, repositories, portfolio visitors, page views, streak and weekly XP.</desc>'
        '<defs>'
        '<linearGradient id="questEdge" x1="0" y1="0" x2="1" y2="1"><stop stop-color="#27e7ff"/><stop offset=".48" stop-color="#9b72ff"/><stop offset="1" stop-color="#ff4fb7"/></linearGradient>'
        '<linearGradient id="questProgress" x1="0" x2="1"><stop stop-color="#27e7ff"/><stop offset=".55" stop-color="#9b72ff"/><stop offset="1" stop-color="#ff4fb7"/></linearGradient>'
        '<radialGradient id="questAura"><stop stop-color="#214b83" stop-opacity=".3"/><stop offset="1" stop-color="#070b16" stop-opacity="0"/></radialGradient>'
        '<pattern id="questGrid" width="28" height="28" patternUnits="userSpaceOnUse"><path d="M28 0H0V28" fill="none" stroke="#8296b5" stroke-opacity=".065"/></pattern>'
        '<filter id="questGlow" x="-20%" y="-80%" width="140%" height="260%"><feGaussianBlur stdDeviation="4" result="blur"/><feMerge><feMergeNode in="blur"/><feMergeNode in="SourceGraphic"/></feMerge></filter>'
        '</defs>'
        '<rect width="1200" height="570" rx="22" fill="#070b16" stroke="#3a4b68" stroke-width="1.4"/>'
        '<rect width="1200" height="570" rx="22" fill="url(#questGrid)"/>'
        '<ellipse cx="610" cy="285" rx="560" ry="340" fill="url(#questAura)"/>'
        '<path d="M24 70H1176" stroke="url(#questEdge)" stroke-width="2" filter="url(#questGlow)"/>'
        '<rect x="27" y="22" width="5" height="28" rx="2" fill="#27e7ff"/>'
        '<text x="46" y="39" fill="#f7fbff" font-family="Arial,sans-serif" font-size="21" font-weight="900" letter-spacing=".8">ASC // DEVELOPER QUEST</text>'
        '<text x="46" y="58" fill="#91a6c4" font-family="Arial,sans-serif" font-size="10" letter-spacing=".9">ENGINEERING ACTIVITY · PORTFOLIO TRAFFIC · PUBLIC DATA</text>'
        '<circle cx="1040" cy="34" r="4" fill="#4ade80"><animate attributeName="opacity" values=".35;1;.35" dur="2s" repeatCount="indefinite"/></circle>'
        '<text x="1053" y="38" fill="#4ade80" font-family="Arial,sans-serif" font-size="10" font-weight="800">SYNCED</text>'
        f'<text x="1170" y="58" text-anchor="end" fill="#7187a5" font-family="Arial,sans-serif" font-size="9">{html.escape(updated_at)}</text>'
        + "".join(blocks)
        + '<path d="M28 282H1172" stroke="#2b3b56" stroke-width="1"/>'
        + '<text x="36" y="314" fill="#e5efff" font-family="Arial,sans-serif" font-size="12" font-weight="800" letter-spacing=".8">7-DAY COMMIT VELOCITY</text>'
        + f'<text x="1164" y="314" text-anchor="end" fill="#91a6c4" font-family="Arial,sans-serif" font-size="9.5">TODAY · {today_count:,} PUBLIC COMMITS</text>'
        + '<path d="M78 356H1122" stroke="#273b59" stroke-width="1" stroke-dasharray="4 7"/>'
        + "".join(bars)
        + '<rect x="78" y="514" width="1044" height="8" rx="4" fill="#18263d"/>'
        + f'<rect x="78" y="514" width="{progress_width:.1f}" height="8" rx="4" fill="url(#questProgress)" filter="url(#questGlow)"/>'
        + f'<text x="78" y="544" fill="#a9bdd7" font-family="Arial,sans-serif" font-size="10" font-weight="700">DAILY MISSION · {today_count:,}/{goal} COMMITS · {goal_percent}% COMPLETE</text>'
        + f'<text x="1122" y="544" text-anchor="end" fill="#a9bdd7" font-family="Arial,sans-serif" font-size="10">WEEKLY XP · {current_xp:,}/500 TO NEXT LEVEL · {xp:,} TOTAL XP</text>'
        + f'<text x="78" y="560" fill="#647d9a" font-family="Arial,sans-serif" font-size="8.5">{html.escape(visitor_status)}</text>'
        + '<text x="1122" y="560" text-anchor="end" fill="#647d9a" font-family="Arial,sans-serif" font-size="8.5">25 XP / PUBLIC COMMIT · PRIVATE ACTIVITY EXCLUDED</text>'
        + "</svg>"
    )

def make_portfolio_views_svg(portfolio_stats: dict | None) -> str:
    """Render a local SVG badge so the README preview never depends on a third-party image endpoint."""
    total = (portfolio_stats or {}).get("total") or {}
    page_views = total.get("pv")
    unique_visitors = total.get("uv")
    if isinstance(page_views, int) and isinstance(unique_visitors, int):
        value = f"{page_views:,}"
        detail = f"{unique_visitors:,} UNIQUE VISITORS"
        status = "LIVE COUNTS"
        accent = "#47e6a3"
    else:
        value = "INITIALIZING"
        detail = "OPEN THE PORTFOLIO TO START TRACKING"
        status = "AWAITING FIRST VISIT"
        accent = "#ffd166"

    return (
        '<svg xmlns="http://www.w3.org/2000/svg" width="560" height="68" viewBox="0 0 560 68" role="img" aria-labelledby="title desc">'
        '<title id="title">Portfolio page views</title>'
        '<desc id="desc">Portfolio visitor counter, refreshed by GitHub Actions.</desc>'
        '<defs><linearGradient id="bg" x1="0" y1="0" x2="1" y2="1">'
        '<stop stop-color="#10172b"/><stop offset="1" stop-color="#17112a"/></linearGradient></defs>'
        '<rect x="1" y="1" width="558" height="66" rx="12" fill="url(#bg)" stroke="#344762"/>'
        '<rect x="13" y="14" width="4" height="40" rx="2" fill="#32d9f5"/>'
        '<text x="30" y="28" fill="#91a6c4" font-family="Arial,sans-serif" font-size="10" font-weight="700" letter-spacing="1.2">LIVE PORTFOLIO PAGE VIEWS</text>'
        f'<text x="30" y="51" fill="#f7fbff" font-family="Arial,sans-serif" font-size="19" font-weight="800">{html.escape(value)}</text>'
        f'<text x="175" y="49" fill="{accent}" font-family="Arial,sans-serif" font-size="9" font-weight="700" letter-spacing=".5">{html.escape(detail)}</text>'
        f'<circle cx="423" cy="28" r="3" fill="{accent}"/>'
        f'<text x="435" y="31" fill="{accent}" font-family="Arial,sans-serif" font-size="8" font-weight="700">{html.escape(status)}</text>'
        '<text x="545" y="57" text-anchor="end" fill="#647d9a" font-family="Arial,sans-serif" font-size="7.5">HOURLY SYNC · ASIA/KOLKATA</text>'
        '</svg>'
    )


def get_portfolio_stats() -> dict | None:
    """Read anonymized 30-day Vercel Web Analytics totals from the portfolio's server-side API."""
    url = "https://adarsh-engineering-portfolio-rust.vercel.app/api/portfolio-stats"
    try:
        request = urllib.request.Request(
            url,
            headers={
                "Accept": "application/json",
                "Cache-Control": "no-cache",
                "User-Agent": "Adarsh-Profile-Sync/1.0",
            },
        )
        with urllib.request.urlopen(request, timeout=20) as response:
            status = getattr(response, "status", 200)
            body = response.read().decode("utf-8", errors="replace").strip()
        if not body:
            print(f"Portfolio analytics API returned an empty HTTP {status} response.")
            return None
        payload = json.loads(body)
        if not isinstance(payload, dict):
            print("Portfolio analytics API returned an unexpected response shape.")
            return None
        if payload.get("status") != "ready":
            print(f"Portfolio analytics is not ready: {payload.get('status', 'unknown')}.")
            return None

        totals = payload.get("total") or {}

        def numeric_count(value):
            if isinstance(value, bool):
                return None
            if isinstance(value, int):
                return value if value >= 0 else None
            if isinstance(value, str) and value.replace(",", "").strip().isdigit():
                return int(value.replace(",", "").strip())
            return None

        uv = numeric_count(totals.get("uv"))
        pv = numeric_count(totals.get("pv"))
        if uv is None and pv is None:
            print("Portfolio analytics API did not return visitor or page-view totals.")
            return None
        payload["total"] = {**totals, "uv": uv, "pv": pv}
        print(
            "Vercel Web Analytics synced: "
            f"{uv if uv is not None else 'visitors pending'} unique visitors and "
            f"{pv if pv is not None else 'page views pending'} page views in the last 30 days."
        )
        return payload
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        try:
            status_payload = json.loads(body)
            state = status_payload.get("status", "unavailable")
        except Exception:
            state = "unavailable"
        print(f"Portfolio analytics API returned HTTP {exc.code} ({state}); visitor totals remain pending.")
        return None
    except Exception as exc:
        print(f"Vercel portfolio analytics unavailable: {exc}")
        return None


def main() -> None:
    DIST.mkdir(parents=True, exist_ok=True)
    now = dt.datetime.now(IST)
    today = now.date()
    since_local = dt.datetime.combine(today - dt.timedelta(days=90), dt.time.min, tzinfo=IST)
    since = iso_utc(since_local)

    # Public endpoints only: no private repo or private contribution data is requested.
    user = api_json(f"https://api.github.com/users/{USERNAME}")
    repositories = list_public_repositories()
    public_count = len(repositories)
    total_stars = sum(int(r.get("stargazers_count", 0)) for r in repositories)
    total_forks = sum(int(r.get("forks_count", 0)) for r in repositories)
    followers = int(user.get("followers", 0))

    visible_repos = [
        r for r in repositories
        if not r.get("fork") and not r.get("archived") and r.get("full_name") != PROFILE_REPO
    ]
    visible_repos.sort(key=lambda r: r.get("pushed_at") or r.get("updated_at") or "", reverse=True)

    recent_rows = []
    for repo in visible_repos[:8]:
        name = html.escape(repo.get("name", "repository"))
        url = repo.get("html_url", "#")
        description = safe_text(repo.get("description"), 94).replace("|", "/")
        language = repo.get("language") or "—"
        stars = int(repo.get("stargazers_count", 0))
        pushed = (repo.get("pushed_at") or repo.get("updated_at") or "")[:10]
        recent_rows.append(
            f"| [{name}]({url}) | {html.escape(description)} | {html.escape(language)} | ★ {stars} | {pushed or '—'} |"
        )
    if not recent_rows:
        recent_rows = ["| No public repositories found | — | — | — | — |"]
    repo_markdown = (
        "| Repository | Description | Primary language | Stars | Last pushed |\n"
        "|---|---|---:|---:|---:|\n"
        + "\n".join(recent_rows)
        + "\n\n<sub>Automatically refreshed hourly from GitHub's public repository API. Private/locked repositories are not queried or displayed.</sub>"
    )

    raw_events = []
    try:
        raw_events = api_json(f"https://api.github.com/users/{USERNAME}/events/public?per_page=100")
    except Exception as exc:
        print(f"Warning: public events endpoint unavailable: {exc}")
    grouped_events = group_public_events(raw_events if isinstance(raw_events, list) else [])

    commits = collect_public_commits(repositories, since)
    daily_counts: dict[dt.date, int] = {}
    for commit in commits:
        day = commit_day(commit)
        if day and 0 <= (today - day).days <= 90:
            daily_counts[day] = daily_counts.get(day, 0) + 1

    # Aggregate real language byte counts for recently pushed public repositories.
    language_bytes: dict[str, int] = {}
    for repo in visible_repos[:24]:
        if not repo.get("languages_url"):
            continue
        try:
            language_map = api_json(repo["languages_url"])
            for language, amount in language_map.items():
                language_bytes[language] = language_bytes.get(language, 0) + int(amount)
        except Exception as exc:
            print(f"Warning: language stats unavailable for {repo.get('full_name')}: {exc}")

    updated_at = now.strftime("%d %b %Y · %I:%M %p IST")
    portfolio_stats = get_portfolio_stats()
    readme = README.read_text(encoding="utf-8")
    if "<!-- PROFILE:RECENT-REPOS:START -->" in readme and "<!-- PROFILE:RECENT-REPOS:END -->" in readme:
        readme = replace_section(
            readme,
            "<!-- PROFILE:RECENT-REPOS:START -->",
            "<!-- PROFILE:RECENT-REPOS:END -->",
            repo_markdown,
        )
    if "<!-- PROFILE:PUBLIC-ACTIVITY:START -->" in readme and "<!-- PROFILE:PUBLIC-ACTIVITY:END -->" in readme:
        activity_markdown = "\n".join(
            f"- **{item['date']}** — {event_label(item)}"
            for item in grouped_events
        ) or "- No recent public events returned by GitHub."
        readme = replace_section(
            readme,
            "<!-- PROFILE:PUBLIC-ACTIVITY:START -->",
            "<!-- PROFILE:PUBLIC-ACTIVITY:END -->",
            activity_markdown + "\n\n<sub>Public events only; repeated same-day pushes are grouped by repository.</sub>",
        )
    if readme != README.read_text(encoding="utf-8"):
        README.write_text(readme, encoding="utf-8")

    (DIST / "profile-stats.svg").write_text(
        make_stats_svg(public_count, total_stars, total_forks, followers), encoding="utf-8"
    )
    (DIST / "languages.svg").write_text(make_languages_svg(language_bytes), encoding="utf-8")
    recent_commit_groups = group_recent_commits(commits, limit=7)
    (DIST / "public-activity.svg").write_text(
        make_activity_svg(recent_commit_groups, updated_at), encoding="utf-8"
    )
    (DIST / "daily-quest.svg").write_text(
        make_daily_quest_svg(today, daily_counts, public_count, total_stars, updated_at, portfolio_stats),
        encoding="utf-8",
    )
    (DIST / "portfolio-views.svg").write_text(
        make_portfolio_views_svg(portfolio_stats), encoding="utf-8"
    )
    print(
        f"Refreshed at {updated_at}: {public_count} public repositories, "
        f"{daily_counts.get(today, 0)} public commits today, "
        f"{sum(daily_counts.get(today - dt.timedelta(days=i), 0) for i in range(7))} public commits in 7 days; "
        f"{(portfolio_stats or {}).get('total', {}).get('uv', 'unavailable')} unique portfolio visitors; "
        f"{(portfolio_stats or {}).get('total', {}).get('pv', 'unavailable')} total page views."
    )


if __name__ == "__main__":
    main()
