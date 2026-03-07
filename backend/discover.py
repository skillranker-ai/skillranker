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
    GITHUB_SEARCH_QUERIES,
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

def fetch_repo_metadata(repo_fullname: str) -> dict:
    """Fetch repository metadata from GitHub API."""
    data = _gh_get(f"{GITHUB_API}/repos/{repo_fullname}")
    if not data:
        return {}

    # Check for CI
    has_ci = False
    workflows = _gh_get(f"{GITHUB_API}/repos/{repo_fullname}/actions/workflows")
    if workflows and workflows.get("total_count", 0) > 0:
        has_ci = True

    # Check for tests (heuristic: look for test directories)
    has_tests = False
    tree = _gh_get(f"{GITHUB_API}/repos/{repo_fullname}/git/trees/HEAD")
    if tree and "tree" in tree:
        for item in tree["tree"]:
            name = item.get("path", "").lower()
            if name in ("tests", "test", "__tests__", "spec", "specs"):
                has_tests = True
                break

    # Contributors count
    contributors = 0
    contribs = _gh_get(f"{GITHUB_API}/repos/{repo_fullname}/contributors",
                       params={"per_page": "1", "anon": "true"})
    if isinstance(contribs, list):
        contributors = len(contribs)
        # GitHub returns Link header for pagination — approximate from first page
        # For accuracy we'd parse Link header, but 1 is minimum

    # Releases
    releases = _gh_get(f"{GITHUB_API}/repos/{repo_fullname}/releases",
                       params={"per_page": "5"})
    release_count = len(releases) if isinstance(releases, list) else 0
    latest_release = ""
    if isinstance(releases, list) and releases:
        latest_release = releases[0].get("tag_name", "")

    return {
        "stars": data.get("stargazers_count", 0),
        "forks": data.get("forks_count", 0),
        "watchers": data.get("subscribers_count", 0),
        "open_issues": data.get("open_issues_count", 0),
        "license": (data.get("license") or {}).get("spdx_id", ""),
        "topics": data.get("topics", []),
        "created_at_gh": data.get("created_at", ""),
        "last_commit": data.get("pushed_at", ""),
        "has_ci": has_ci,
        "has_tests": has_tests,
        "contributors": max(contributors, 1),
        "release_count": release_count,
        "latest_release": latest_release,
    }


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
# Discovery: GitHub Code Search
# ---------------------------------------------------------------------------

def discover_from_search(run: DiscoveryRun) -> list[dict]:
    """Search GitHub for repos containing SKILL.md files."""
    found = []
    seen_slugs = set()

    for query in GITHUB_SEARCH_QUERIES:
        print(f"  Searching: {query}", file=sys.stderr)
        data = _gh_get(
            f"{GITHUB_API}/search/code",
            params={"q": query, "per_page": "100"},
        )
        if not data or "items" not in data:
            run.errors.append(f"Search failed: {query}")
            continue

        for item in data["items"]:
            repo = item.get("repository", {})
            repo_fullname = repo.get("full_name", "")
            path = item.get("path", "")

            if not repo_fullname or not path.endswith("SKILL.md"):
                continue

            slug = _make_slug(repo_fullname, path)
            if slug in seen_slugs:
                continue
            seen_slugs.add(slug)

            found.append({
                "repo_fullname": repo_fullname,
                "repo_url": f"https://github.com/{repo_fullname}",
                "skill_path": path,
                "slug": slug,
                "source_type": SourceType.GITHUB_SEARCH.value,
            })

        # Be gentle with search API
        time.sleep(2)

    print(f"  Search found {len(found)} skills", file=sys.stderr)
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

def persist_discoveries(discoveries: list[dict], run: DiscoveryRun) -> tuple[int, int]:
    """Save discovered skills to DB.  Returns (total, new)."""
    session = get_session()
    total = len(discoveries)
    new_count = 0

    for disc in discoveries:
        slug = disc["slug"]
        existing = session.exec(
            select(Skill).where(Skill.slug == slug)
        ).first()

        if existing:
            # Update source if we found it from a better source
            continue

        # Fetch SKILL.md content
        skill_md = _gh_get_file(disc["repo_fullname"], disc["skill_path"])
        readme = _gh_get_file(disc["repo_fullname"], "README.md")

        # Extract name from SKILL.md frontmatter or directory name
        name = _extract_skill_name(skill_md, disc["skill_path"], disc["repo_fullname"])

        # Fetch repo metadata
        print(f"  Fetching metadata: {disc['repo_fullname']}", file=sys.stderr)
        meta = fetch_repo_metadata(disc["repo_fullname"])

        # Analyze structure
        structure = analyze_skill_structure(disc["repo_fullname"], disc["skill_path"])

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
