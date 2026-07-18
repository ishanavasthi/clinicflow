"""SQLite engine and session helpers."""
from __future__ import annotations

from collections.abc import Iterator

from sqlmodel import Session, SQLModel, create_engine

from config import get_settings

_settings = get_settings()

# check_same_thread=False lets the same SQLite file be used across FastAPI's
# threadpool workers. Fine for a single-node demo backend.
engine = create_engine(
    _settings.database_url,
    echo=False,
    connect_args={"check_same_thread": False},
)


def init_db() -> None:
    """Create tables. Models must be imported before this runs so SQLModel
    has registered them on its metadata."""
    import models  # noqa: F401  (import for side effect: table registration)

    SQLModel.metadata.create_all(engine)


def get_session() -> Iterator[Session]:
    """FastAPI dependency that yields a scoped session."""
    with Session(engine) as session:
        yield session
