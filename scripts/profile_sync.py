#!/usr/bin/env python3
"""Refresh a GitHub profile using public repositories and public events only.

The activity game card is built from commit records authored by the profile owner
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


def make_activity_svg(items: list[dict], updated_at: str) -> str:
    height = 120 + max(1, len(items)) * 43
    pieces = []
    palette = ["#22d3ee", "#f472b6", "#a78bfa", "#4ade80", "#fbbf24", "#60a5fa", "#fb7185"]
    for i, item in enumerate(items):
        y = 88 + i * 43
        repo_name = item["repo"]
        label = event_label(item)
        url = f"https://github.com/{repo_name}"
        pieces.append(
            f'<circle cx="30" cy="{y - 4}" r="6" fill="{palette[i % len(palette)]}"/>'
            f'<text x="50" y="{y}" fill="#e2e8f0" font-family="Arial,sans-serif" font-size="13">{html.escape(safe_text(label, 100))}</text>'
            f'<text x="50" y="{y + 17}" fill="#7890aa" font-family="Arial,sans-serif" font-size="10">{html.escape(item["date"])} · <tspan fill="#22d3ee">{html.escape(repo_name)}</tspan></text>'
        )
    if not pieces:
        pieces.append('<text x="30" y="100" fill="#9fb5cf" font-family="Arial,sans-serif" font-size="14">No recent public events returned by GitHub.</text>')
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="1000" height="{height}" viewBox="0 0 1000 {height}">'
        '<rect width="1000" height="100%" rx="18" fill="#070b16" stroke="#26364e"/>'
        '<text x="28" y="38" fill="#f8fafc" font-family="Arial,sans-serif" font-size="19" font-weight="700">LATEST PUBLIC ACTIVITY</text>'
        f'<text x="28" y="58" fill="#8fa8c3" font-family="Arial,sans-serif" font-size="11">Grouped by repository and India date · synced {html.escape(updated_at)}</text>'
        f'<path d="M30 78V{height - 28}" stroke="#354967" stroke-width="2"/>'
        + "".join(pieces)
        + "</svg>"
    )


def make_daily_quest_svg(
    today: dt.date,
    daily_counts: dict[dt.date, int],
    public_repos: int,
    stars: int,
    updated_at: str,
) -> str:
    today_count = daily_counts.get(today, 0)
    week = [today - dt.timedelta(days=i) for i in range(6, -1, -1)]
    weekly_total = sum(daily_counts.get(day, 0) for day in week)
    xp = weekly_total * 25
    level = xp // 500 + 1
    progress_xp = xp % 500
    goal = 5
    goal_width = min(1.0, today_count / goal) * 390
    streak_end = today if today_count else today - dt.timedelta(days=1)
    streak = 0
    check = streak_end
    while daily_counts.get(check, 0) > 0 and streak < 90:
        streak += 1
        check -= dt.timedelta(days=1)

    cards = [
        ("TODAY'S COMMITS", str(today_count), "#22d3ee", "PUBLIC REPOS ONLY"),
        ("PUBLIC REPOSITORIES", f"{public_repos:,}", "#f472b6", "ACCOUNT-WIDE"),
        ("CURRENT STREAK", f"{streak} DAY" if streak == 1 else f"{streak} DAYS", "#4ade80", "CONSECUTIVE ACTIVE DAYS"),
        (f"LVL {level} · WEEKLY XP", f"{xp:,} XP", "#a78bfa", "25 XP PER PUBLIC COMMIT"),
    ]
    blocks = []
    for i, (label, value, accent, subtitle) in enumerate(cards):
        x = 26 + i * 240
        blocks.append(
            f'<g transform="translate({x},84)"><rect width="220" height="105" rx="13" fill="#0d1628" stroke="{accent}" stroke-opacity=".65"/>'
            f'<text x="15" y="23" fill="#9bb0ca" font-family="Arial,sans-serif" font-size="10" font-weight="700" letter-spacing=".6">{html.escape(label)}</text>'
            f'<text x="15" y="62" fill="#f8fafc" font-family="Arial,sans-serif" font-size="27" font-weight="800">{html.escape(value)}</text>'
            f'<text x="15" y="84" fill="{accent}" font-family="Arial,sans-serif" font-size="9">{html.escape(subtitle)}</text></g>'
        )

    chart_x, chart_y, chart_w, chart_h = 38, 247, 924, 102
    max_value = max([daily_counts.get(day, 0) for day in week] + [1])
    bars = []
    bar_w = 72
    gap = 52
    for i, day in enumerate(week):
        count = daily_counts.get(day, 0)
        h = max(4, chart_h * count / max_value) if count else 4
        x = chart_x + 44 + i * (bar_w + gap)
        y = chart_y + chart_h - h
        accent = "#22d3ee" if day == today else "#8b5cf6"
        bars.append(
            f'<rect x="{x}" y="{y:.1f}" width="{bar_w}" height="{h:.1f}" rx="7" fill="{accent}" opacity=".92"/>'
            f'<text x="{x + bar_w/2}" y="{y - 8:.1f}" text-anchor="middle" fill="#e2e8f0" font-family="Arial,sans-serif" font-size="11" font-weight="700">{count}</text>'
            f'<text x="{x + bar_w/2}" y="{chart_y + chart_h + 22}" text-anchor="middle" fill="#9fb5cf" font-family="Arial,sans-serif" font-size="10">{day.strftime("%a")}</text>'
        )

    return (
        '<svg xmlns="http://www.w3.org/2000/svg" width="1000" height="405" viewBox="0 0 1000 405">'
        '<defs><linearGradient id="questGrad" x1="0" x2="1"><stop stop-color="#22d3ee"/><stop offset=".55" stop-color="#8b5cf6"/><stop offset="1" stop-color="#f472b6"/></linearGradient>'
        '<filter id="glow"><feGaussianBlur stdDeviation="4" result="b"/><feMerge><feMergeNode in="b"/><feMergeNode in="SourceGraphic"/></feMerge></filter></defs>'
        '<rect width="1000" height="405" rx="18" fill="#070b16" stroke="#384763" stroke-width="1.2"/>'
        '<path d="M18 65H982" stroke="url(#questGrad)" stroke-width="2" opacity=".8"/>'
        '<text x="28" y="35" fill="#f8fafc" font-family="Arial,sans-serif" font-size="19" font-weight="800" letter-spacing=".5">⚡ DEVELOPER QUEST // PUBLIC ACTIVITY</text>'
        f'<text x="970" y="36" text-anchor="end" fill="#4ade80" font-family="Arial,sans-serif" font-size="10">LIVE SYNC · {html.escape(updated_at)}</text>'
        + "".join(blocks)
        + '<text x="30" y="226" fill="#dbeafe" font-family="Arial,sans-serif" font-size="12" font-weight="700">7-DAY ACTIVITY MAP</text>'
        + '<text x="970" y="226" text-anchor="end" fill="#8fa8c3" font-family="Arial,sans-serif" font-size="10">TODAY GOAL: 5 PUBLIC COMMITS</text>'
        + f'<rect x="30" y="360" width="940" height="9" rx="5" fill="#1a2940"/>'
        + f'<rect x="30" y="360" width="{goal_width:.1f}" height="9" rx="5" fill="url(#questGrad)" filter="url(#glow)"/>'
        + f'<text x="30" y="389" fill="#9fb5cf" font-family="Arial,sans-serif" font-size="10">DAILY QUEST: {today_count}/{goal} commits · {min(100, int(today_count / goal * 100))}% COMPLETE</text>'
        + f'<text x="970" y="389" text-anchor="end" fill="#7187a5" font-family="Arial,sans-serif" font-size="9">GAME XP = 25 × public commits this week · not an official GitHub metric</text>'
        + "".join(bars)
        + "</svg>"
    )


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
    (DIST / "public-activity.svg").write_text(
        make_activity_svg(grouped_events, updated_at), encoding="utf-8"
    )
    (DIST / "daily-quest.svg").write_text(
        make_daily_quest_svg(today, daily_counts, public_count, total_stars, updated_at),
        encoding="utf-8",
    )
    print(
        f"Refreshed at {updated_at}: {public_count} public repositories, "
        f"{daily_counts.get(today, 0)} public commits today, "
        f"{sum(daily_counts.get(today - dt.timedelta(days=i), 0) for i in range(7))} public commits in 7 days."
    )


if __name__ == "__main__":
    main()
