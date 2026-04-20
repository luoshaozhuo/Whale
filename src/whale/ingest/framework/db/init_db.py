"""Database initialization entrypoint for the ingest framework."""

from __future__ import annotations

from importlib import import_module

from whale.ingest.framework.db.base import Base
from whale.ingest.framework.db.session import engine


def init_db() -> None:
    """Create all ORM tables defined for the ingest framework."""
    import_module("whale.ingest.framework.db.models.models")
    Base.metadata.create_all(bind=engine)


if __name__ == "__main__":
    init_db()
