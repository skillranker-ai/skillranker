"""
Discovery layer — finds Claude Code skills from multiple sources.

Sources:
  1. GitHub Code Search (SKILL.md files)
  2. GitHub Repository Search (topics, descriptions)
  3. Awesome-lists (known curated repositories)
  4. Local scan (already cloned repos)

Usage:
    python -m backend.discover
    python -m backend.discover --source awesome
    python -m backend.discover --source search
"""

from __future__ import annotations

import argparse
import base64
import json
import re
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from typing import Optional

from sqlmodel import select

from backend.config import (
    GITHUB_API,
    GITHUB_AWESOME_LISTS,
    GITHUB_TOKEN,
)
from backend.db import get_session, init_db
from backend.models import DiscoveryRun, Skill, SkillStatus, SourceType


# ---------------------------------------------------------------------------
# GitHub API helpers
# ---------------------------------------------------------------------------

def _gh_headers() -> dict[str, str]:
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "skillranker",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if GITHUB_TOKEN:
        headers["Authorization"] = f"Bearer {GITHUB_TOKEN}"
    return headers


def _gh_get(url: str, params: Optional[dict] = None) -> Optional[dict]:
    """GET request to GitHub API with rate-limit awareness."""
    if params:
        qs = "&".join(f"{k}={urllib.request.quote(str(v))}" for k, v in params.items())
        url = f"{url}?{qs}"
    req = urllib.request.Request(url, headers=_gh_headers())
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            remaining = resp.headers.get("X-RateLimit-Remaining", "?")
            if remaining != "?" and int(remaining) < 5:
                reset = int(resp.headers.get("X-RateLimit-Reset", 0))
                wait = max(reset - int(time.time()), 1)
                print(f"  Rate limit near — sleeping {wait}s", file=sys.stderr)
                time.sleep(wait)
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        if e.code == 403:
            reset = int(e.headers.get("X-RateLimit-Reset", 0))
            wait = max(reset - int(time.time()), 60)
            print(f"  Rate limited — sleeping {wait}s", file=sys.stderr)
            time.sleep(wait)
            return _gh_get(url)  # retry once
        print(f"  GitHub API error {e.code}: {url}", file=sys.stderr)
        return None
    except Exception as e:
        print(f"  Request error: {e}", file=sys.stderr)
        return None


def _gh_get_file(repo_fullname: str, path: str) -> Optional[str]:
    """Fetch a file's content from a GitHub repo."""
    data = _gh_get(f"{GITHUB_API}/repos/{repo_fullname}/contents/{path}")
    if data and data.get("encoding") == "base64" and data.get("content"):
        return base64.b64decode(data["content"]).decode("utf-8", errors="replace")
    return None


def _make_slug(repo_fullname: str, skill_path: str) -> str:
    """Create a unique slug from repo + path."""
    parts = repo_fullname.replace("/", "-")
    if skill_path and skill_path != "SKILL.md":
        subdir = skill_path.rsplit("/SKILL.md", 1)[0].replace("/", "-")
        return f"{parts}--{subdir}".lower()
    return parts.lower()


# ---------------------------------------------------------------------------
# Repo metadata fetcher
# ---------------------------------------------------------------------------

def fetch_repo_metadata(repo_fullname: str, full: bool = False) -> dict:
    """Fetch repository metadata from GitHub API.

    Args:
        full: If True, also fetch CI, tests, contributors, releases
              (5 extra API calls). If False, only the repo endpoint (1 call).
    """
    data = _gh_get(f"{GITHUB_API}/repos/{repo_fullname}")
    if not data:
        return {}

    result = {
        "stars": data.get("stargazers_count", 0),
        "forks": data.get("forks_count", 0),
        "watchers": data.get("subscribers_count", 0),
        "open_issues": data.get("open_issues_count", 0),
        "license": (data.get("license") or {}).get("spdx_id", ""),
        "topics": data.get("topics", []),
        "created_at_gh": data.get("created_at", ""),
        "last_commit": data.get("pushed_at", ""),
        "has_ci": False,
        "has_tests": False,
        "contributors": 1,
        "release_count": 0,
        "latest_release": "",
    }

    if not full:
        return result

    # --- Extra calls (only in full mode) ---

    # Check for CI
    workflows = _gh_get(f"{GITHUB_API}/repos/{repo_fullname}/actions/workflows")
    if workflows and workflows.get("total_count", 0) > 0:
        result["has_ci"] = True

    # Check for tests (heuristic: look for test directories)
    tree = _gh_get(f"{GITHUB_API}/repos/{repo_fullname}/git/trees/HEAD")
    if tree and "tree" in tree:
        for item in tree["tree"]:
            name = item.get("path", "").lower()
            if name in ("tests", "test", "__tests__", "spec", "specs"):
                result["has_tests"] = True
                break

    # Contributors count
    contribs = _gh_get(f"{GITHUB_API}/repos/{repo_fullname}/contributors",
                       params={"per_page": "1", "anon": "true"})
    if isinstance(contribs, list):
        result["contributors"] = max(len(contribs), 1)

    # Releases
    releases = _gh_get(f"{GITHUB_API}/repos/{repo_fullname}/releases",
                       params={"per_page": "5"})
    if isinstance(releases, list):
        result["release_count"] = len(releases)
        if releases:
            result["latest_release"] = releases[0].get("tag_name", "")

    return result


# ---------------------------------------------------------------------------
# Skill structure analysis
# ---------------------------------------------------------------------------

def analyze_skill_structure(repo_fullname: str, skill_path: str) -> dict:
    """Check what dirs exist next to the SKILL.md using Tree API (1 call)."""
    parent = skill_path.rsplit("/", 1)[0] if "/" in skill_path else ""
    prefix = f"{parent}/" if parent else ""

    data = _gh_get(
        f"{GITHUB_API}/repos/{repo_fullname}/git/trees/HEAD",
        params={"recursive": "1"},
    )
    if not data or "tree" not in data:
        return {}

    # Collect sibling directory names
    sibling_dirs = set()
    for item in data["tree"]:
        path = item.get("path", "")
        if item.get("type") == "tree" and path.startswith(prefix):
            relative = path[len(prefix):]
            if "/" not in relative:  # direct child only
                sibling_dirs.add(relative.lower())

    return {
        "has_references": "references" in sibling_dirs or "refs" in sibling_dirs,
        "has_scripts": "scripts" in sibling_dirs,
        "has_examples": "examples" in sibling_dirs or "example" in sibling_dirs,
        "has_templates": "templates" in sibling_dirs or "template" in sibling_dirs,
    }


# ---------------------------------------------------------------------------
# Discovery: GitHub Code Search — FULL SCAN
# ---------------------------------------------------------------------------

def _search_code_paginated(query: str, max_pages: int = 10) -> list[dict]:
    """Paginated GitHub Code Search. Returns list of {repo, path} dicts."""
    results = []
    for page in range(1, max_pages + 1):
        data = _gh_get(
            f"{GITHUB_API}/search/code",
            params={"q": query, "per_page": "100", "page": str(page)},
        )
        if not data or "items" not in data:
            break

        for item in data["items"]:
            repo = item.get("repository", {})
            results.append({
                "repo_fullname": repo.get("full_name", ""),
                "path": item.get("path", ""),
            })

        total = data.get("total_count", 0)
        fetched = page * 100
        if fetched >= total or fetched >= 1000:  # GitHub hard limit
            break
        time.sleep(3)  # search API rate: 10 req/min

    return results


def _generate_date_segments() -> list[str]:
    """Generate date range segments for repository search to bypass 1000 result limit.

    Used by Strategy 3 (repo search) where created: qualifier works.
    """
    segments = ["created:<2024-01-01"]
    year = 2024
    month = 1
    now = datetime.now(timezone.utc)
    while True:
        end_year = year + (month // 12)
        end_month = (month % 12) + 1
        start = f"{year}-{month:02d}-01"
        end = f"{end_year}-{end_month:02d}-01"
        segments.append(f"created:{start}..{end}")
        month += 1
        if year == now.year and month > now.month:
            break
        if month > 12:
            month = 1
            year += 1
    return segments


def discover_from_search(run: DiscoveryRun) -> list[dict]:
    """Full GitHub scan for SKILL.md files.

    Strategy:
      1. filename:SKILL.md — finds EVERY file named SKILL.md on GitHub
         Segmented by date to bypass 1000 result limit
      2. Topic search — repos tagged with skill-related topics
      3. Repo description search — repos mentioning "claude skill" etc.
    """
    found = []
    seen_slugs = set()

    def _add(repo_fullname: str, path: str, source: str = SourceType.GITHUB_SEARCH.value):
        if not repo_fullname or not path.endswith("SKILL.md"):
            return
        slug = _make_slug(repo_fullname, path)
        if slug in seen_slugs:
            return
        seen_slugs.add(slug)
        found.append({
            "repo_fullname": repo_fullname,
            "repo_url": f"https://github.com/{repo_fullname}",
            "skill_path": path,
            "slug": slug,
            "source_type": source,
        })

    # --- Strategy 1: filename:SKILL.md (the big gun) ---
    # Code Search API does NOT support created: qualifier, so no date segmentation.
    # If results exceed 1000, pagination handles up to that cap.
    print("  Strategy 1: filename:SKILL.md (full GitHub scan)", file=sys.stderr)
    results = _search_code_paginated("filename:SKILL.md")
    for r in results:
        _add(r["repo_fullname"], r["path"])
    print(f"    -> {len(results)} results", file=sys.stderr)

    # --- Strategy 2: Topic search ---
    # Find repos tagged with relevant topics (different API, different rate limit)
    print("  Strategy 2: Topic search", file=sys.stderr)
    topic_queries = [
        "topic:claude-code-skill",
        "topic:claude-skills",
        "topic:agent-skills",
        "topic:claude-code-plugin",
        "topic:claude-agent-skill",
    ]
    for tq in topic_queries:
        print(f"    Topic: {tq}", file=sys.stderr)
        for page in range(1, 6):
            data = _gh_get(
                f"{GITHUB_API}/search/repositories",
                params={"q": tq, "per_page": "100", "page": str(page)},
            )
            if not data or "items" not in data:
                break
            for repo in data["items"]:
                fullname = repo.get("full_name", "")
                if fullname:
                    # Use Tree API to find SKILL.md in this repo
                    paths = _find_skill_mds_via_tree(fullname)
                    for p in paths:
                        _add(fullname, p)
            if len(data["items"]) < 100:
                break
            time.sleep(2)

    # --- Strategy 3: Repo description search ---
    print("  Strategy 3: Repo description search", file=sys.stderr)
    desc_queries = [
        "claude skill in:description",
        "claude code skill in:description",
        "agent skill claude in:description,readme",
        "SKILL.md claude in:readme",
        "claude-code skill in:name,description",
    ]
    for dq in desc_queries:
        print(f"    Query: {dq}", file=sys.stderr)
        for page in range(1, 4):
            data = _gh_get(
                f"{GITHUB_API}/search/repositories",
                params={"q": dq, "per_page": "100", "page": str(page)},
            )
            if not data or "items" not in data:
                break
            for repo in data["items"]:
                fullname = repo.get("full_name", "")
                if fullname:
                    paths = _find_skill_mds_via_tree(fullname)
                    for p in paths:
                        _add(fullname, p)
            if len(data["items"]) < 100:
                break
            time.sleep(2)

    print(f"  Total discovered: {len(found)} unique skills", file=sys.stderr)
    return found


# ---------------------------------------------------------------------------
# Discovery: Awesome lists
# ---------------------------------------------------------------------------

def _find_skill_mds_via_tree(repo_fullname: str) -> list[str]:
    """Use Git Tree API to find all SKILL.md files in a repo (1 API call)."""
    data = _gh_get(
        f"{GITHUB_API}/repos/{repo_fullname}/git/trees/HEAD",
        params={"recursive": "1"},
    )
    if not data or "tree" not in data:
        return []
    return [
        item["path"]
        for item in data["tree"]
        if item.get("type") == "blob" and item["path"].endswith("SKILL.md")
    ]


def discover_from_awesome(run: DiscoveryRun) -> list[dict]:
    """Parse awesome-lists for skill repository links.

    Uses Git Tree API — 1 request per repo instead of N content requests.
    """
    found = []
    seen_slugs = set()

    for list_repo in GITHUB_AWESOME_LISTS:
        print(f"  Scanning awesome list: {list_repo}", file=sys.stderr)
        readme = _gh_get_file(list_repo, "README.md")
        if not readme:
            run.errors.append(f"Could not fetch README: {list_repo}")
            continue

        # Extract GitHub repo URLs
        urls = re.findall(
            r"https://github\.com/([a-zA-Z0-9_.-]+/[a-zA-Z0-9_.-]+)", readme
        )
        unique_repos = list(dict.fromkeys(urls))
        print(f"    Found {len(unique_repos)} repo links", file=sys.stderr)

        for target_repo in unique_repos:
            if target_repo == list_repo:
                continue

            # One API call to get ALL files in the repo
            skill_paths = _find_skill_mds_via_tree(target_repo)
            if not skill_paths:
                continue

            print(f"    {target_repo}: {len(skill_paths)} SKILL.md(s)", file=sys.stderr)
            for path in skill_paths:
                slug = _make_slug(target_repo, path)
                if slug in seen_slugs:
                    continue
                seen_slugs.add(slug)
                found.append({
                    "repo_fullname": target_repo,
                    "repo_url": f"https://github.com/{target_repo}",
                    "skill_path": path,
                    "slug": slug,
                    "source_type": SourceType.GITHUB_AWESOME.value,
                })

            time.sleep(0.3)

    print(f"  Awesome lists found {len(found)} skills", file=sys.stderr)
    return found


# ---------------------------------------------------------------------------
# Persist discoveries
# ---------------------------------------------------------------------------

def persist_discoveries(
    discoveries: list[dict],
    run: DiscoveryRun,
    full_metadata: bool = False,
) -> tuple[int, int]:
    """Save discovered skills to DB.  Returns (total, new).

    Args:
        full_metadata: If True, fetch CI/tests/contributors/releases per repo
                       (5 extra API calls each). Default False for speed.
    """
    session = get_session()
    total = len(discoveries)
    new_count = 0

    # Cache repo metadata to avoid duplicate fetches
    # (many skills come from the same repo)
    _meta_cache: dict[str, dict] = {}
    _structure_cache: dict[str, dict] = {}

    for disc in discoveries:
        slug = disc["slug"]
        existing = session.exec(
            select(Skill).where(Skill.slug == slug)
        ).first()

        if existing:
            continue

        repo = disc["repo_fullname"]

        # Fetch SKILL.md content
        skill_md = _gh_get_file(repo, disc["skill_path"])
        readme = _gh_get_file(repo, "README.md") if repo not in _meta_cache else None

        # Extract name from SKILL.md frontmatter or directory name
        name = _extract_skill_name(skill_md, disc["skill_path"], repo)

        # Fetch repo metadata (cached per repo)
        if repo not in _meta_cache:
            print(f"  Fetching metadata: {repo}", file=sys.stderr)
            _meta_cache[repo] = fetch_repo_metadata(repo, full=full_metadata)
        meta = _meta_cache[repo]

        # Analyze structure (cached per repo)
        cache_key = f"{repo}:{disc['skill_path']}"
        if cache_key not in _structure_cache:
            structure = analyze_skill_structure(repo, disc["skill_path"])
            _structure_cache[cache_key] = structure
        else:
            structure = _structure_cache[cache_key]

        skill = Skill(
            name=name,
            slug=slug,
            repo_url=disc["repo_url"],
            repo_fullname=disc["repo_fullname"],
            skill_path=disc["skill_path"],
            source_type=disc["source_type"],
            status=SkillStatus.NEW.value,
            skill_md_raw=skill_md or "",
            readme_raw=readme or "",
            skill_md_lines=len((skill_md or "").split("\n")),
            has_skill_md=bool(skill_md),
            # GitHub metrics
            stars=meta.get("stars", 0),
            forks=meta.get("forks", 0),
            watchers=meta.get("watchers", 0),
            open_issues=meta.get("open_issues", 0),
            contributors=meta.get("contributors", 0),
            last_commit=meta.get("last_commit"),
            created_at_gh=meta.get("created_at_gh"),
            license=meta.get("license", ""),
            topics=meta.get("topics", []),
            has_tests=meta.get("has_tests", False),
            has_ci=meta.get("has_ci", False),
            release_count=meta.get("release_count", 0),
            latest_release=meta.get("latest_release", ""),
            # Structure
            has_references=structure.get("has_references", False),
            has_scripts=structure.get("has_scripts", False),
            has_examples=structure.get("has_examples", False),
            has_templates=structure.get("has_templates", False),
        )

        session.add(skill)
        new_count += 1
        time.sleep(0.3)  # rate limit courtesy

    run.skills_found = total
    run.skills_new = new_count
    run.finished_at = datetime.now(timezone.utc).isoformat()
    session.add(run)
    session.commit()
    session.close()

    return total, new_count


def _extract_skill_name(
    skill_md: Optional[str],
    skill_path: str,
    repo_fullname: str,
) -> str:
    """Extract skill name from YAML frontmatter or fall back to path/repo."""
    if skill_md:
        for line in skill_md.split("\n")[:20]:
            line = line.strip()
            if line.startswith("name:"):
                name = line.split(":", 1)[1].strip().strip('"').strip("'")
                if name:
                    return name

    # Fallback: directory name or repo name
    if "/" in skill_path:
        parts = skill_path.split("/")
        # e.g. skills/my-skill/SKILL.md → my-skill
        if len(parts) >= 2:
            return parts[-2]

    return repo_fullname.split("/")[-1]


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Discover Claude Code skills")
    parser.add_argument(
        "--source",
        choices=["all", "search", "awesome"],
        default="all",
        help="Discovery source",
    )
    args = parser.parse_args()

    init_db()

    run = DiscoveryRun(source=args.source)
    discoveries = []

    if args.source in ("all", "search"):
        print("=== GitHub Code Search ===", file=sys.stderr)
        discoveries.extend(discover_from_search(run))

    if args.source in ("all", "awesome"):
        print("=== Awesome Lists ===", file=sys.stderr)
        discoveries.extend(discover_from_awesome(run))

    print(f"\n=== Persisting {len(discoveries)} discoveries ===", file=sys.stderr)
    total, new = persist_discoveries(discoveries, run)
    print(f"Done: {total} found, {new} new", file=sys.stderr)


if __name__ == "__main__":
    main()
