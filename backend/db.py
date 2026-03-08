"""Database setup — SQLite for dev, Postgres for prod."""

import sys
from pathlib import Path

from sqlmodel import SQLModel, Session, create_engine

from backend.config import DATA_DIR, DATABASE_URL

# Ensure data dir exists for SQLite
DATA_DIR.mkdir(parents=True, exist_ok=True)

_connect_args = {}
if DATABASE_URL.startswith("sqlite"):
    _connect_args["check_same_thread"] = False

engine = create_engine(DATABASE_URL, connect_args=_connect_args)


def run_migrations() -> None:
    """Run Alembic migrations (upgrade to head)."""
    try:
        from alembic.config import Config
        from alembic import command

        alembic_cfg = Config(str(Path(__file__).parent.parent / "alembic.ini"))
        alembic_cfg.set_main_option("sqlalchemy.url", DATABASE_URL)
        command.upgrade(alembic_cfg, "head")
    except Exception as e:
        print(f"  Migration warning: {e}", file=sys.stderr)
        print("  Falling back to create_all", file=sys.stderr)


def init_db() -> None:
    """Initialize database — run migrations then create any missing tables."""
    run_migrations()
    SQLModel.metadata.create_all(engine)


def get_session() -> Session:
    return Session(engine)
