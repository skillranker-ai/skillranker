"""Tests for backend.dedup — deduplication logic."""

from sqlmodel import select

from backend.dedup import dedup_skills
from backend.models import Skill, SkillStatus
from tests.conftest import make_skill

# We need to patch get_session to use the test session
import backend.dedup as dedup_module


def _get_status(session, slug: str) -> str:
    """Re-query skill status after dedup (which closes its own session)."""
    skill = session.exec(select(Skill).where(Skill.slug == slug)).first()
    return skill.status


def _patch_session(session, monkeypatch):
    """Patch get_session to return test session, prevent close from detaching."""
    original_close = session.close
    monkeypatch.setattr(session, "close", lambda: None)  # prevent close
    monkeypatch.setattr(dedup_module, "get_session", lambda: session)


def test_exact_duplicate_detected(session, monkeypatch):
    """Skills with identical near_hash should be deduplicated."""
    _patch_session(session, monkeypatch)

    skill1 = make_skill(
        slug="owner-repo--skill-a",
        name="skill-a",
        near_hash="abc123",
        status=SkillStatus.EVALUATED.value,
        score_final=80.0,
        stars=200,
    )
    skill2 = make_skill(
        slug="other-repo--skill-b",
        name="skill-b",
        repo_fullname="other/repo",
        near_hash="abc123",  # same hash
        status=SkillStatus.EVALUATED.value,
        score_final=50.0,
        stars=100,
    )
    session.add(skill1)
    session.add(skill2)
    session.commit()

    rejected = dedup_skills()
    assert rejected == 1

    assert _get_status(session, "owner-repo--skill-a") == SkillStatus.EVALUATED.value
    assert _get_status(session, "other-repo--skill-b") == SkillStatus.REJECTED.value


def test_unique_skills_kept(session, monkeypatch):
    """Skills with different near_hash should all survive."""
    _patch_session(session, monkeypatch)

    skill1 = make_skill(slug="a", near_hash="hash1", status=SkillStatus.EVALUATED.value)
    skill2 = make_skill(slug="b", near_hash="hash2", status=SkillStatus.EVALUATED.value)
    session.add(skill1)
    session.add(skill2)
    session.commit()

    rejected = dedup_skills()
    assert rejected == 0


def test_best_score_wins(session, monkeypatch):
    """The highest-scored duplicate should be kept."""
    _patch_session(session, monkeypatch)

    for i, score in enumerate([30.0, 90.0, 60.0]):
        s = make_skill(
            slug=f"repo--skill-{i}",
            name=f"skill-{i}",
            near_hash="same_hash",
            status=SkillStatus.EVALUATED.value,
            score_final=score,
        )
        session.add(s)
    session.commit()

    rejected = dedup_skills()
    assert rejected == 2

    # skill-1 (score 90.0) should survive
    assert _get_status(session, "repo--skill-1") == SkillStatus.EVALUATED.value
    assert _get_status(session, "repo--skill-0") == SkillStatus.REJECTED.value
    assert _get_status(session, "repo--skill-2") == SkillStatus.REJECTED.value


def test_already_rejected_not_counted(session, monkeypatch):
    """Already-rejected skills should not participate in dedup."""
    _patch_session(session, monkeypatch)

    skill1 = make_skill(
        slug="a", near_hash="dup", status=SkillStatus.EVALUATED.value, score_final=50.0
    )
    skill2 = make_skill(
        slug="b", near_hash="dup", status=SkillStatus.REJECTED.value, score_final=80.0
    )
    session.add(skill1)
    session.add(skill2)
    session.commit()

    rejected = dedup_skills()
    assert rejected == 0  # skill2 already rejected, skill1 is sole survivor
