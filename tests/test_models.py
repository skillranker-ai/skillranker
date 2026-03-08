"""Tests for backend.models — model defaults and enums."""

from backend.models import Skill, SkillStatus, SourceType


def test_skill_defaults():
    """Skill should have sensible default values."""
    skill = Skill(name="test", slug="test-slug")
    assert skill.status == SkillStatus.NEW.value
    assert skill.stars == 0
    assert skill.score_final == 0.0
    assert skill.domains == []
    assert skill.tags == []
    assert skill.skill_md_changed is True
    assert skill.content_hash == ""
    assert skill.near_hash == ""


def test_skill_status_enum_values():
    """SkillStatus enum should have expected string values."""
    assert SkillStatus.NEW.value == "new"
    assert SkillStatus.EVALUATED.value == "evaluated"
    assert SkillStatus.ENRICHED.value == "enriched"
    assert SkillStatus.PUBLISHED.value == "published"
    assert SkillStatus.REJECTED.value == "rejected"


def test_source_type_enum_values():
    """SourceType enum should have expected string values."""
    assert SourceType.GITHUB_SEARCH.value == "github_search"
    assert SourceType.GITHUB_AWESOME.value == "github_awesome"
    assert SourceType.MANUAL.value == "manual"


def test_skill_roundtrip(session):
    """Skill should persist and load correctly from DB."""
    skill = Skill(
        name="roundtrip-test",
        slug="roundtrip-test",
        stars=42,
        domains=["coding", "testing"],
        tags=["a", "b", "c"],
        content_hash="abc123",
        near_hash="def456",
    )
    session.add(skill)
    session.commit()

    loaded = session.get(Skill, skill.id)
    assert loaded is not None
    assert loaded.name == "roundtrip-test"
    assert loaded.stars == 42
    assert loaded.domains == ["coding", "testing"]
    assert loaded.content_hash == "abc123"
    assert loaded.near_hash == "def456"
