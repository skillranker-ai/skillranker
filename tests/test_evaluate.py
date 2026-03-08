"""Tests for backend.evaluate — scoring functions and quality filter."""

import math

from backend.config import SCORE_WEIGHTS
from backend.evaluate import (
    compute_final_score,
    score_adoption,
    score_documentation,
    score_maintenance,
    score_structure,
    should_reject,
)
from backend.models import Skill, SkillStatus
from tests.conftest import make_skill


def test_score_weights_sum_to_one():
    """All scoring weights must sum to 1.0."""
    total = sum(SCORE_WEIGHTS.values())
    assert abs(total - 1.0) < 0.001, f"Weights sum to {total}, expected 1.0"


def test_score_adoption_dilution(session):
    """Stars should be diluted when multiple skills share a repo."""
    # Create 4 skills in the same repo
    for i in range(4):
        skill = make_skill(
            slug=f"owner-repo--skill-{i}",
            name=f"skill-{i}",
            stars=1000,
            forks=100,
        )
        session.add(skill)
    session.commit()

    skill = session.exec(
        Skill.__table__.select().where(Skill.slug == "owner-repo--skill-0")
    )
    skill_obj = make_skill(stars=1000, forks=100, repo_fullname="owner/repo")

    # With session (dilution active): 4 skills → sqrt(4) = 2x dilution
    score_with_dilution = score_adoption(skill_obj, session=session)

    # Without session (no dilution)
    score_no_dilution = score_adoption(skill_obj, session=None)

    assert score_with_dilution < score_no_dilution, (
        f"Diluted score ({score_with_dilution}) should be less than "
        f"undiluted ({score_no_dilution})"
    )


def test_score_adoption_single_skill(session):
    """A solo skill in a repo should not be diluted."""
    skill = make_skill(slug="solo-repo--skill", repo_fullname="solo/repo", stars=100)
    session.add(skill)
    session.commit()

    score_with_session = score_adoption(skill, session=session)
    score_without_session = score_adoption(skill, session=None)

    # Single skill → sqrt(1) = 1 → no dilution
    assert abs(score_with_session - score_without_session) < 0.01


def test_should_reject_short_skill():
    """Skills with fewer than 10 lines should be rejected."""
    skill = make_skill(skill_md_lines=5, skill_md_raw="short")
    assert should_reject(skill) is True


def test_should_reject_empty_content():
    """Skills with fewer than 200 chars should be rejected."""
    skill = make_skill(skill_md_lines=20, skill_md_raw="x" * 100)
    assert should_reject(skill) is True


def test_should_reject_passes_good_skill():
    """A well-formed skill should pass the quality gate."""
    skill = make_skill(skill_md_lines=50, skill_md_raw="x" * 500)
    assert should_reject(skill) is False


def test_compute_final_score_nonzero():
    """Final score should be positive for a skill with nonzero hard metrics."""
    skill = make_skill()
    skill.score_maintenance = 50.0
    skill.score_documentation = 60.0
    skill.score_completeness = 40.0
    skill.score_adoption = 30.0
    skill.score_structure = 45.0
    result = compute_final_score(skill)
    assert result > 0


def test_score_documentation_rewards_skill_md():
    """Having a SKILL.md should boost documentation score."""
    skill_with = make_skill(has_skill_md=True, skill_md_lines=100)
    skill_without = make_skill(has_skill_md=False, skill_md_lines=0, skill_md_raw="")

    assert score_documentation(skill_with) > score_documentation(skill_without)


def test_score_maintenance_recent_commit():
    """Recent commits should score higher than old ones."""
    from datetime import datetime, timezone, timedelta

    recent = (datetime.now(timezone.utc) - timedelta(days=3)).isoformat()
    old = (datetime.now(timezone.utc) - timedelta(days=400)).isoformat()

    skill_recent = make_skill(last_commit=recent)
    skill_old = make_skill(last_commit=old)

    assert score_maintenance(skill_recent) > score_maintenance(skill_old)
