"""Baseline schema — skills + discovery_runs tables.

Revision ID: 001
Revises:
Create Date: 2025-03-09
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Skip creation if tables already exist (existing databases)
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing = inspector.get_table_names()

    if "skills" not in existing:
        op.create_table(
            "skills",
            sa.Column("id", sa.Integer, primary_key=True),
            sa.Column("name", sa.String, nullable=False, index=True),
            sa.Column("slug", sa.String, nullable=False, unique=True, index=True),
            sa.Column("repo_url", sa.String, server_default=""),
            sa.Column("repo_fullname", sa.String, server_default=""),
            sa.Column("skill_path", sa.String, server_default=""),
            sa.Column("source_type", sa.String, server_default="github_search"),
            sa.Column("status", sa.String, server_default="new", index=True),
            sa.Column("skill_md_raw", sa.Text, server_default=""),
            sa.Column("readme_raw", sa.Text, server_default=""),
            sa.Column("stars", sa.Integer, server_default="0"),
            sa.Column("forks", sa.Integer, server_default="0"),
            sa.Column("watchers", sa.Integer, server_default="0"),
            sa.Column("open_issues", sa.Integer, server_default="0"),
            sa.Column("contributors", sa.Integer, server_default="0"),
            sa.Column("last_commit", sa.String, nullable=True),
            sa.Column("last_commit_sha", sa.String, nullable=True),
            sa.Column("created_at_gh", sa.String, nullable=True),
            sa.Column("license", sa.String, server_default=""),
            sa.Column("topics", sa.JSON, server_default="[]"),
            sa.Column("has_tests", sa.Boolean, server_default="0"),
            sa.Column("has_ci", sa.Boolean, server_default="0"),
            sa.Column("release_count", sa.Integer, server_default="0"),
            sa.Column("latest_release", sa.String, server_default=""),
            sa.Column("has_skill_md", sa.Boolean, server_default="0"),
            sa.Column("has_references", sa.Boolean, server_default="0"),
            sa.Column("has_scripts", sa.Boolean, server_default="0"),
            sa.Column("has_examples", sa.Boolean, server_default="0"),
            sa.Column("has_templates", sa.Boolean, server_default="0"),
            sa.Column("skill_md_lines", sa.Integer, server_default="0"),
            sa.Column("score_maintenance", sa.Float, server_default="0.0"),
            sa.Column("score_documentation", sa.Float, server_default="0.0"),
            sa.Column("score_completeness", sa.Float, server_default="0.0"),
            sa.Column("score_adoption", sa.Float, server_default="0.0"),
            sa.Column("score_structure", sa.Float, server_default="0.0"),
            sa.Column("score_ai_quality", sa.Float, server_default="0.0"),
            sa.Column("score_ai_usefulness", sa.Float, server_default="0.0"),
            sa.Column("score_ai_novelty", sa.Float, server_default="0.0"),
            sa.Column("score_ai_description", sa.Float, server_default="0.0"),
            sa.Column("score_ai_reusability", sa.Float, server_default="0.0"),
            sa.Column("score_final", sa.Float, server_default="0.0", index=True),
            sa.Column("domains", sa.JSON, server_default="[]"),
            sa.Column("tags", sa.JSON, server_default="[]"),
            sa.Column("ai_summary", sa.Text, server_default=""),
            sa.Column("ai_strengths", sa.JSON, server_default="[]"),
            sa.Column("ai_weaknesses", sa.JSON, server_default="[]"),
            sa.Column("ai_use_cases", sa.JSON, server_default="[]"),
            sa.Column("skill_md_changed", sa.Boolean, server_default="1"),
            sa.Column("discovered_at", sa.String, nullable=False),
            sa.Column("evaluated_at", sa.String, nullable=True),
            sa.Column("enriched_at", sa.String, nullable=True),
            sa.Column("published_at", sa.String, nullable=True),
        )

    if "discovery_runs" not in existing:
        op.create_table(
            "discovery_runs",
            sa.Column("id", sa.Integer, primary_key=True),
            sa.Column("started_at", sa.String, nullable=False),
            sa.Column("finished_at", sa.String, nullable=True),
            sa.Column("source", sa.String, server_default=""),
            sa.Column("skills_found", sa.Integer, server_default="0"),
            sa.Column("skills_new", sa.Integer, server_default="0"),
            sa.Column("errors", sa.JSON, server_default="[]"),
        )


def downgrade() -> None:
    op.drop_table("skills")
    op.drop_table("discovery_runs")
