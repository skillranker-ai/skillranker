"""Data models for SkillRanker.

Uses SQLModel (Pydantic + SQLAlchemy) for DB models and plain Pydantic
for API / export schemas.  Falls back to pure SQLite so the pipeline
runs without a Postgres install.
"""

from __future__ import annotations

import enum
from datetime import datetime, timezone
from typing import Optional

from pydantic import BaseModel, Field
from sqlmodel import SQLModel, Field as SQLField, Column, JSON


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class SkillStatus(str, enum.Enum):
    NEW = "new"
    EVALUATED = "evaluated"
    ENRICHED = "enriched"
    PUBLISHED = "published"
    REJECTED = "rejected"


class SourceType(str, enum.Enum):
    GITHUB_SEARCH = "github_search"
    GITHUB_AWESOME = "github_awesome"
    LOCAL_SCAN = "local_scan"
    MANUAL = "manual"
    WEB_SCRAPE = "web_scrape"


# ---------------------------------------------------------------------------
# DB models
# ---------------------------------------------------------------------------

class Skill(SQLModel, table=True):
    """Core skill record in the database."""
    __tablename__ = "skills"

    id: Optional[int] = SQLField(default=None, primary_key=True)

    # Identity
    name: str = SQLField(index=True)
    slug: str = SQLField(index=True, unique=True)
    repo_url: str = SQLField(default="", index=True)
    repo_fullname: str = SQLField(default="")  # owner/repo
    skill_path: str = SQLField(default="")  # path to SKILL.md in repo
    source_type: str = SQLField(default=SourceType.GITHUB_SEARCH.value)
    status: str = SQLField(default=SkillStatus.NEW.value, index=True)

    # Raw content
    skill_md_raw: str = SQLField(default="")
    readme_raw: str = SQLField(default="")

    # GitHub metrics
    stars: int = SQLField(default=0)
    forks: int = SQLField(default=0)
    watchers: int = SQLField(default=0)
    open_issues: int = SQLField(default=0)
    contributors: int = SQLField(default=0)
    last_commit: Optional[str] = SQLField(default=None)
    last_commit_sha: Optional[str] = SQLField(default=None)  # HEAD sha — skip re-eval if unchanged
    created_at_gh: Optional[str] = SQLField(default=None)
    license: str = SQLField(default="")
    topics: list[str] = SQLField(default=[], sa_column=Column(JSON))
    has_tests: bool = SQLField(default=False)
    has_ci: bool = SQLField(default=False)
    release_count: int = SQLField(default=0)
    latest_release: str = SQLField(default="")

    # Structure flags
    has_skill_md: bool = SQLField(default=False)
    has_references: bool = SQLField(default=False)
    has_scripts: bool = SQLField(default=False)
    has_examples: bool = SQLField(default=False)
    has_templates: bool = SQLField(default=False)
    skill_md_lines: int = SQLField(default=0)

    # Hard scores (0-100 each)
    score_maintenance: float = SQLField(default=0.0)
    score_documentation: float = SQLField(default=0.0)
    score_completeness: float = SQLField(default=0.0)
    score_adoption: float = SQLField(default=0.0)
    score_structure: float = SQLField(default=0.0)

    # Soft scores from AI (0-100 each)
    score_ai_quality: float = SQLField(default=0.0)
    score_ai_usefulness: float = SQLField(default=0.0)
    score_ai_novelty: float = SQLField(default=0.0)
    score_ai_description: float = SQLField(default=0.0)
    score_ai_reusability: float = SQLField(default=0.0)

    # Final composite score
    score_final: float = SQLField(default=0.0, index=True)

    # AI-generated content
    domains: list[str] = SQLField(default=[], sa_column=Column(JSON))
    tags: list[str] = SQLField(default=[], sa_column=Column(JSON))
    ai_summary: str = SQLField(default="")
    ai_strengths: list[str] = SQLField(default=[], sa_column=Column(JSON))
    ai_weaknesses: list[str] = SQLField(default=[], sa_column=Column(JSON))
    ai_use_cases: list[str] = SQLField(default=[], sa_column=Column(JSON))

    # Change tracking
    skill_md_changed: bool = SQLField(default=True)  # True = needs AI re-enrichment
    content_hash: str = SQLField(default="")  # SHA256 of skill_md_raw (first 16 hex chars)
    enriched_content_hash: str = SQLField(default="")  # content_hash when last enriched
    near_hash: str = SQLField(default="", index=True)  # normalized hash for near-dedup

    # Metadata
    discovered_at: str = SQLField(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    evaluated_at: Optional[str] = SQLField(default=None)
    enriched_at: Optional[str] = SQLField(default=None)
    published_at: Optional[str] = SQLField(default=None)


class DiscoveryRun(SQLModel, table=True):
    """Tracks each discovery run for auditability."""
    __tablename__ = "discovery_runs"

    id: Optional[int] = SQLField(default=None, primary_key=True)
    started_at: str = SQLField(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    finished_at: Optional[str] = SQLField(default=None)
    source: str = SQLField(default="")
    skills_found: int = SQLField(default=0)
    skills_new: int = SQLField(default=0)
    errors: list[str] = SQLField(default=[], sa_column=Column(JSON))


# ---------------------------------------------------------------------------
# Export / API schemas (not stored in DB)
# ---------------------------------------------------------------------------

class SkillCard(BaseModel):
    """Schema for a single skill card on the frontend."""
    id: int
    name: str
    slug: str
    repo_url: str
    repo_fullname: str
    stars: int
    forks: int
    license: str
    domains: list[str]
    tags: list[str]
    score_final: float
    score_maintenance: float
    score_documentation: float
    score_completeness: float
    score_adoption: float
    score_structure: float
    score_ai_quality: float
    score_ai_usefulness: float
    score_ai_novelty: float
    score_ai_description: float
    score_ai_reusability: float
    ai_summary: str
    ai_strengths: list[str]
    ai_weaknesses: list[str]
    ai_use_cases: list[str]
    last_commit: Optional[str]
    latest_release: str
    has_skill_md: bool
    has_references: bool
    has_scripts: bool
    has_examples: bool
    status: str


class DomainRanking(BaseModel):
    """A ranked list of skills for one domain."""
    domain: str
    skills: list[SkillCard]
    total: int
    updated_at: str


class SiteCatalog(BaseModel):
    """Top-level export for the static site."""
    generated_at: str
    total_skills: int
    domains: list[DomainRanking]
    top_overall: list[SkillCard]
    recently_added: list[SkillCard]
    fastest_growing: list[SkillCard]
