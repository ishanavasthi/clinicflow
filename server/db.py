"""SQLite engine and session helpers."""
from __future__ import annotations

from collections.abc import Iterator

from sqlmodel import Session, SQLModel, create_engine
from sqlalchemy import text

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
    # create_all does not add constraints to existing tables. Fail explicitly if
    # legacy duplicate appointments prevent upgrading; never delete patient data.
    with engine.begin() as conn:
        duplicates = conn.execute(text(
            "SELECT slot_id FROM appointment GROUP BY slot_id HAVING COUNT(*) > 1 LIMIT 1"
        )).first()
        if duplicates:
            raise RuntimeError("Existing duplicate appointments require reconciliation before startup")
        conn.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS uq_appointment_slot ON appointment(slot_id)"))


def get_session() -> Iterator[Session]:
    """FastAPI dependency that yields a scoped session."""
    with Session(engine) as session:
        yield session
