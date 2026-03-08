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
        if e.code in (403, 429):
            reset = int(e.headers.get("X-RateLimit-Reset", 0))
            wait = max(reset - int(time.time()), 60)
            print(f"  Rate limited ({e.code}) — sleeping {wait}s", file=sys.stderr)
            time.sleep(wait)
            return _gh_get(url)  # retry once
        if e.code == 401:
            # Could be rate limit exhaustion or bad token
            remaining = e.headers.get("X-RateLimit-Remaining", "?")
            if remaining != "?" and int(remaining) == 0:
                reset = int(e.headers.get("X-RateLimit-Reset", 0))
                wait = max(reset - int(time.time()), 60)
                print(f"  Rate limit exhausted — sleeping {wait}s", file=sys.stderr)
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
        "last_commit_sha": "",
        "has_ci": False,
        "has_tests": False,
        "contributors": 1,
        "release_count": 0,
        "latest_release": "",
    }

    # Fetch HEAD sha (1 extra call, but essential for change detection)
    ref_data = _gh_get(f"{GITHUB_API}/repos/{repo_fullname}/git/ref/heads/{data.get('default_branch', 'main')}")
    if ref_data and "object" in ref_data:
        result["last_commit_sha"] = ref_data["object"].get("sha", "")

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

def analyze_skill_structure(repo_fullname: str, skill_path: str, tree_data: dict | None = None) -> dict:
    """Check what dirs exist next to the SKILL.md.

    Args:
        tree_data: Pre-fetched tree data to avoid extra API call.
    """
    parent = skill_path.rsplit("/", 1)[0] if "/" in skill_path else ""
    prefix = f"{parent}/" if parent else ""

    if tree_data is None:
        tree_data = _gh_get(
            f"{GITHUB_API}/repos/{repo_fullname}/git/trees/HEAD",
            params={"recursive": "1"},
        )
    if not tree_data or "tree" not in tree_data:
        return {}

    # Collect sibling directory names
    sibling_dirs = set()
    for item in tree_data["tree"]:
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


# Cache for tree data fetched during discovery (reused in persist)
_tree_cache: dict[str, dict] = {}


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

    # --- Strategy 1: .claude/skills/ directory (standard Claude Code location) ---
    # This is where Claude Code stores skills. The code search is case-insensitive
    # so we filter results to only include files named exactly SKILL.md.
    print("  Strategy 1: .claude/skills/ (standard location)", file=sys.stderr)
    results = _search_code_paginated("path:.claude/skills filename:SKILL.md")
    added_s1 = 0
    for r in results:
        # Filter: must be a file named exactly SKILL.md (not skill.md, not .backup)
        basename = r["path"].rsplit("/", 1)[-1] if "/" in r["path"] else r["path"]
        if basename == "SKILL.md":
            _add(r["repo_fullname"], r["path"])
            added_s1 += 1
    print(f"    -> {len(results)} raw, {added_s1} valid SKILL.md files", file=sys.stderr)

    # --- Strategy 1b: SKILL.md with Claude-related frontmatter ---
    # Catches standalone SKILL.md files outside .claude/skills/ that are
    # actually Claude Code skills (contain "name:" and "description:").
    print("  Strategy 1b: Standalone Claude skills", file=sys.stderr)
    for sq in [
        'filename:SKILL.md "name:" "description:" path:/',
        'filename:SKILL.md "name:" "instructions"',
    ]:
        results = _search_code_paginated(sq, max_pages=3)
        added = 0
        for r in results:
            basename = r["path"].rsplit("/", 1)[-1] if "/" in r["path"] else r["path"]
            if basename == "SKILL.md" and ".claude/" not in r["path"]:
                _add(r["repo_fullname"], r["path"])
                added += 1
        print(f"    {sq[:60]}: {added} new", file=sys.stderr)

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

    # --- Strategy 3: Targeted repo name search ---
    # Find repos explicitly named as Claude skill collections.
    print("  Strategy 3: Targeted repo search", file=sys.stderr)
    desc_queries = [
        '"claude" "skill" in:name',
        '"claude-code" in:name fork:false',
    ]
    for dq in desc_queries:
        print(f"    Query: {dq}", file=sys.stderr)
        data = _gh_get(
            f"{GITHUB_API}/search/repositories",
            params={"q": dq, "per_page": "100", "page": "1"},
        )
        if not data or "items" not in data:
            continue
        for repo in data["items"]:
            fullname = repo.get("full_name", "")
            if fullname:
                paths = _find_skill_mds_via_tree(fullname)
                for p in paths:
                    _add(fullname, p)
        time.sleep(2)

    print(f"  Total discovered: {len(found)} unique skills", file=sys.stderr)
    return found


# ---------------------------------------------------------------------------
# Discovery: Awesome lists
# ---------------------------------------------------------------------------

def _find_skill_mds_via_tree(repo_fullname: str) -> list[str]:
    """Use Git Tree API to find all SKILL.md files in a repo (1 API call)."""
    if repo_fullname in _tree_cache:
        data = _tree_cache[repo_fullname]
    else:
        data = _gh_get(
            f"{GITHUB_API}/repos/{repo_fullname}/git/trees/HEAD",
            params={"recursive": "1"},
        )
        if data and "tree" in data:
            _tree_cache[repo_fullname] = data
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
    limit: int = 0,
) -> tuple[int, int]:
    """Save discovered skills to DB.  Returns (total, new).

    Args:
        full_metadata: If True, fetch CI/tests/contributors/releases per repo
                       (5 extra API calls each). Default False for speed.
        limit: Max skills to persist (0=unlimited).
    """
    session = get_session()
    total = len(discoveries)
    new_count = 0
    skipped = 0

    # Cache repo metadata to avoid duplicate fetches
    # (many skills come from the same repo)
    _meta_cache: dict[str, dict] = {}
    _structure_cache: dict[str, dict] = {}
    _readme_cache: dict[str, str] = {}

    print(f"  Persisting {total} discoveries...", file=sys.stderr)

    for i, disc in enumerate(discoveries):
        slug = disc["slug"]
        existing = session.exec(
            select(Skill).where(Skill.slug == slug)
        ).first()

        if existing:
            skipped += 1
            continue

        if limit and new_count >= limit:
            print(f"  Reached persist limit ({limit}), stopping.", file=sys.stderr)
            break

        repo = disc["repo_fullname"]

        # Fetch SKILL.md content
        skill_md = _gh_get_file(repo, disc["skill_path"])

        # Validate this is actually a Claude Code skill
        if not _is_claude_skill(skill_md or "", disc["skill_path"]):
            continue

        # Cache README per repo (1 call per repo, not per skill)
        if repo not in _readme_cache:
            _readme_cache[repo] = _gh_get_file(repo, "README.md") or ""
        readme = _readme_cache[repo]

        # Extract name from SKILL.md frontmatter or directory name
        name = _extract_skill_name(skill_md, disc["skill_path"], repo)

        # Fetch repo metadata (cached per repo)
        if repo not in _meta_cache:
            print(f"  Fetching metadata: {repo} ({new_count+1}/{total})", file=sys.stderr)
            _meta_cache[repo] = fetch_repo_metadata(repo, full=full_metadata)
        meta = _meta_cache[repo]

        # Analyze structure — reuse cached tree data from discovery phase
        cache_key = f"{repo}:{disc['skill_path']}"
        if cache_key not in _structure_cache:
            tree_data = _tree_cache.get(repo)
            structure = analyze_skill_structure(repo, disc["skill_path"], tree_data=tree_data)
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
            last_commit_sha=meta.get("last_commit_sha", ""),
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

        # Progress update every 25 skills
        if new_count % 25 == 0:
            print(f"  Progress: {new_count} new skills persisted ({i+1}/{total} processed)", file=sys.stderr)
            session.commit()  # commit in batches

    print(f"  Done: {new_count} new, {skipped} existing, {total - new_count - skipped} failed", file=sys.stderr)
    run.skills_found = total
    run.skills_new = new_count
    run.finished_at = datetime.now(timezone.utc).isoformat()
    session.add(run)
    session.commit()
    session.close()

    return total, new_count


def refresh_existing_skills() -> tuple[int, int]:
    """Re-check existing skills for repo changes using HEAD sha.

    Compares stored last_commit_sha with current HEAD. If different,
    refreshes metadata and resets status to NEW for re-evaluation.

    Returns (checked, updated).
    """
    session = get_session()
    skills = session.exec(select(Skill)).all()

    # Group skills by repo to avoid duplicate API calls
    repo_skills: dict[str, list[Skill]] = {}
    for skill in skills:
        repo_skills.setdefault(skill.repo_fullname, []).append(skill)

    checked = 0
    updated = 0

    for repo, repo_skill_list in repo_skills.items():
        checked += 1

        # Get current repo info
        data = _gh_get(f"{GITHUB_API}/repos/{repo}")
        if not data:
            continue

        default_branch = data.get("default_branch", "main")
        ref_data = _gh_get(f"{GITHUB_API}/repos/{repo}/git/ref/heads/{default_branch}")
        if not ref_data or "object" not in ref_data:
            continue

        current_sha = ref_data["object"].get("sha", "")
        stored_sha = repo_skill_list[0].last_commit_sha or ""

        if current_sha and current_sha == stored_sha:
            continue  # No changes — skip

        # Repo changed — refresh metadata for all skills in this repo
        print(f"  Repo changed: {repo} (old={stored_sha[:8]}.. new={current_sha[:8]}..)", file=sys.stderr)
        meta = fetch_repo_metadata(repo)
        meta["last_commit_sha"] = current_sha

        for skill in repo_skill_list:
            skill.stars = meta.get("stars", 0)
            skill.forks = meta.get("forks", 0)
            skill.watchers = meta.get("watchers", 0)
            skill.open_issues = meta.get("open_issues", 0)
            skill.last_commit = meta.get("last_commit")
            skill.last_commit_sha = current_sha
            skill.topics = meta.get("topics", [])
            skill.license = meta.get("license", "")

            # Re-fetch SKILL.md content
            new_content = _gh_get_file(repo, skill.skill_path)
            if new_content:
                skill.skill_md_raw = new_content
                skill.skill_md_lines = len(new_content.split("\n"))

            # Reset to NEW so it gets re-evaluated
            if skill.status != SkillStatus.NEW.value:
                skill.status = SkillStatus.NEW.value

            session.add(skill)
            updated += 1

        if checked % 10 == 0:
            session.commit()

    session.commit()
    session.close()
    print(f"  Refresh: {checked} repos checked, {updated} skills updated", file=sys.stderr)
    return checked, updated


def _is_claude_skill(skill_md: str, skill_path: str) -> bool:
    """Check if a SKILL.md is likely a Claude Code skill (not a random file)."""
    if not skill_md:
        return False

    # Standard Claude Code skill location
    if ".claude/skills/" in skill_path:
        return True

    content_lower = skill_md.lower()

    # Check for skill frontmatter fields (name: + description:)
    has_name = "name:" in content_lower[:500]
    has_desc = "description:" in content_lower[:500]
    if has_name and has_desc:
        return True

    # Check for Claude/agent related content
    claude_markers = ["claude", "agent", "instructions", "skill"]
    matches = sum(1 for m in claude_markers if m in content_lower)
    return matches >= 2


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
