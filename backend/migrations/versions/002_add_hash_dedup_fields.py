"""Add content_hash, enriched_content_hash, near_hash fields.

Revision ID: 002
Revises: 001
Create Date: 2025-03-09
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "002"
down_revision: Union[str, None] = "001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _column_exists(table: str, column: str) -> bool:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = [c["name"] for c in inspector.get_columns(table)]
    return column in columns


def upgrade() -> None:
    if not _column_exists("skills", "content_hash"):
        op.add_column("skills", sa.Column("content_hash", sa.String, server_default=""))
    if not _column_exists("skills", "enriched_content_hash"):
        op.add_column("skills", sa.Column("enriched_content_hash", sa.String, server_default=""))
    if not _column_exists("skills", "near_hash"):
        op.add_column("skills", sa.Column("near_hash", sa.String, server_default="", index=True))


def downgrade() -> None:
    op.drop_column("skills", "near_hash")
    op.drop_column("skills", "enriched_content_hash")
    op.drop_column("skills", "content_hash")
