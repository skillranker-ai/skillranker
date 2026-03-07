"""Database setup — SQLite for dev, Postgres for prod."""

from sqlmodel import SQLModel, Session, create_engine

from backend.config import DATA_DIR, DATABASE_URL

# Ensure data dir exists for SQLite
DATA_DIR.mkdir(parents=True, exist_ok=True)

_connect_args = {}
if DATABASE_URL.startswith("sqlite"):
    _connect_args["check_same_thread"] = False

engine = create_engine(DATABASE_URL, connect_args=_connect_args)


def init_db() -> None:
    SQLModel.metadata.create_all(engine)


def get_session() -> Session:
    return Session(engine)
