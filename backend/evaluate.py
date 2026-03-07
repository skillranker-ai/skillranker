"""
Evaluation layer — computes hard metric scores for each skill.

Scores are 0-100 per dimension.  No AI calls here — pure rules.

Usage:
    python -m backend.evaluate
"""

from __future__ import annotations

import math
import sys
from datetime import datetime, timezone

from sqlmodel import select

from backend.config import SCORE_WEIGHTS
from backend.db import get_session, init_db
from backend.models import Skill, SkillStatus


def _days_since(iso_date: str | None) -> float:
    """Days between now and an ISO date string.  Returns 9999 if None."""
    if not iso_date:
        return 9999
    try:
        dt = datetime.fromisoformat(iso_date.replace("Z", "+00:00"))
        return (datetime.now(timezone.utc) - dt).total_seconds() / 86400
    except Exception:
        return 9999


def score_maintenance(skill: Skill) -> float:
    """Score based on recency of commits, releases, issue activity."""
    s = 0.0

    # Last commit recency (0-40)
    days = _days_since(skill.last_commit)
    if days < 7:
        s += 40
    elif days < 30:
        s += 35
    elif days < 90:
        s += 25
    elif days < 180:
        s += 15
    elif days < 365:
        s += 5

    # Release frequency (0-30)
    if skill.release_count >= 10:
        s += 30
    elif skill.release_count >= 5:
        s += 25
    elif skill.release_count >= 2:
        s += 15
    elif skill.release_count >= 1:
        s += 10

    # Contributors (0-20)
    if skill.contributors >= 10:
        s += 20
    elif skill.contributors >= 5:
        s += 15
    elif skill.contributors >= 2:
        s += 10
    elif skill.contributors >= 1:
        s += 5

    # Issue ratio — low open issues relative to stars is good (0-10)
    if skill.stars > 0:
        ratio = skill.open_issues / skill.stars
        if ratio < 0.01:
            s += 10
        elif ratio < 0.05:
            s += 7
        elif ratio < 0.1:
            s += 3

    return min(s, 100)


def score_documentation(skill: Skill) -> float:
    """Score based on SKILL.md quality and README presence."""
    s = 0.0

    # SKILL.md exists (0-30)
    if skill.has_skill_md:
        s += 30

    # SKILL.md length — longer is better up to a point (0-30)
    lines = skill.skill_md_lines
    if lines >= 200:
        s += 30
    elif lines >= 100:
        s += 25
    elif lines >= 50:
        s += 15
    elif lines >= 20:
        s += 10

    # SKILL.md content quality heuristics (0-25)
    md = skill.skill_md_raw.lower()
    if "```" in md:
        s += 5   # has code examples
    if "## " in md or "### " in md:
        s += 5   # has structure
    if "example" in md or "usage" in md:
        s += 5   # has usage section
    if "trigger" in md or "use when" in md or "invoke" in md:
        s += 5   # has trigger description
    if "description:" in md:
        s += 5   # has frontmatter

    # README exists (0-15)
    if skill.readme_raw:
        readme_lines = len(skill.readme_raw.split("\n"))
        if readme_lines >= 50:
            s += 15
        elif readme_lines >= 20:
            s += 10
        elif readme_lines >= 5:
            s += 5

    return min(s, 100)


def score_completeness(skill: Skill) -> float:
    """Score based on skill structure completeness."""
    s = 0.0

    if skill.has_skill_md:
        s += 25
    if skill.has_references:
        s += 25
    if skill.has_scripts:
        s += 20
    if skill.has_examples:
        s += 15
    if skill.has_templates:
        s += 15

    return min(s, 100)


def score_adoption(skill: Skill) -> float:
    """Score based on community adoption signals."""
    s = 0.0

    # Stars (0-50) — log-scaled
    if skill.stars > 0:
        star_score = math.log10(skill.stars) / 5.0 * 50  # 100k stars = 50
        s += min(star_score, 50)

    # Forks (0-30) — log-scaled
    if skill.forks > 0:
        fork_score = math.log10(skill.forks) / 4.0 * 30  # 10k forks = 30
        s += min(fork_score, 30)

    # Watchers (0-20)
    if skill.watchers > 0:
        watch_score = math.log10(skill.watchers) / 4.0 * 20
        s += min(watch_score, 20)

    return min(s, 100)


def score_structure(skill: Skill) -> float:
    """Score based on engineering quality signals."""
    s = 0.0

    # License (0-30)
    if skill.license and skill.license not in ("NOASSERTION", ""):
        s += 30

    # Tests (0-25)
    if skill.has_tests:
        s += 25

    # CI/CD (0-25)
    if skill.has_ci:
        s += 25

    # Topics/tags (0-10)
    if len(skill.topics) >= 3:
        s += 10
    elif len(skill.topics) >= 1:
        s += 5

    # Repo age — established repos score higher (0-10)
    days = _days_since(skill.created_at_gh)
    if days != 9999:
        if days >= 365:
            s += 10
        elif days >= 180:
            s += 7
        elif days >= 30:
            s += 3

    return min(s, 100)


def compute_final_score(skill: Skill) -> float:
    """Weighted combination of all scores."""
    w = SCORE_WEIGHTS
    return (
        skill.score_maintenance * w["maintenance"]
        + skill.score_documentation * w["documentation"]
        + skill.score_completeness * w["completeness"]
        + skill.score_adoption * w["adoption"]
        + skill.score_structure * w["structure"]
        + skill.score_ai_quality * w["ai_quality"]
        + skill.score_ai_usefulness * w["ai_usefulness"]
        + skill.score_ai_novelty * w["ai_novelty"]
    )


def evaluate_all() -> int:
    """Evaluate all skills that need scoring.  Returns count evaluated."""
    session = get_session()
    skills = session.exec(
        select(Skill).where(
            Skill.status.in_([SkillStatus.NEW.value, SkillStatus.EVALUATED.value])
        )
    ).all()

    count = 0
    for skill in skills:
        skill.score_maintenance = score_maintenance(skill)
        skill.score_documentation = score_documentation(skill)
        skill.score_completeness = score_completeness(skill)
        skill.score_adoption = score_adoption(skill)
        skill.score_structure = score_structure(skill)
        skill.score_final = compute_final_score(skill)

        if skill.status == SkillStatus.NEW.value:
            skill.status = SkillStatus.EVALUATED.value
        skill.evaluated_at = datetime.now(timezone.utc).isoformat()

        session.add(skill)
        count += 1

    session.commit()
    session.close()
    return count


def main():
    init_db()
    print("Evaluating skills...", file=sys.stderr)
    count = evaluate_all()
    print(f"Evaluated {count} skills", file=sys.stderr)


if __name__ == "__main__":
    main()
