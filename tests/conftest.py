"""Shared fixtures for SkillRanker tests."""

import os
import pytest
from sqlmodel import SQLModel, Session, create_engine

# Force SQLite in-memory for tests
os.environ["DATABASE_URL"] = "sqlite://"

from backend.models import Skill, SkillStatus


@pytest.fixture
def engine():
    """Create a fresh in-memory SQLite engine per test."""
    eng = create_engine("sqlite://", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(eng)
    yield eng
    SQLModel.metadata.drop_all(eng)


@pytest.fixture
def session(engine):
    """Provide a session bound to the test engine."""
    with Session(engine) as sess:
        yield sess


def make_skill(**overrides) -> Skill:
    """Factory for creating Skill objects with sensible defaults."""
    defaults = {
        "name": "test-skill",
        "slug": "owner-repo--test-skill",
        "repo_url": "https://github.com/owner/repo",
        "repo_fullname": "owner/repo",
        "skill_path": ".claude/skills/test-skill/SKILL.md",
        "source_type": "github_search",
        "status": SkillStatus.NEW.value,
        "skill_md_raw": "name: test-skill\ndescription: A test skill\n\n## Instructions\n\nDo something useful.\n" * 5,
        "readme_raw": "# Repo\n\nA test repository.",
        "skill_md_lines": 50,
        "has_skill_md": True,
        "stars": 100,
        "forks": 10,
        "watchers": 5,
        "open_issues": 2,
        "contributors": 3,
        "last_commit": "2025-03-01T00:00:00Z",
        "license": "MIT",
    }
    defaults.update(overrides)
    return Skill(**defaults)
