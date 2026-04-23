"""SQLAlchemy engine and session helpers for the ingest framework."""

from __future__ import annotations

from collections.abc import Generator
from contextlib import contextmanager
from pathlib import Path

from sqlalchemy import URL, create_engine
from sqlalchemy.orm import Session, sessionmaker

from whale.ingest.config import CONFIG


def create_db_url() -> URL:
    """Build the database URL from `CONFIG` and environment variables."""
    database = CONFIG.database.database
    if CONFIG.database.drivername.startswith("sqlite"):
        database_path = Path(database)
        if not database_path.is_absolute():
            database_path = (Path(__file__).resolve().parents[2] / database_path).resolve()
        return URL.create(
            drivername=CONFIG.database.drivername,
            database=str(database_path),
        )

    return URL.create(
        drivername=CONFIG.database.drivername,
        username=CONFIG.database.username,
        password=CONFIG.database.password,
        host=CONFIG.database.host,
        port=CONFIG.database.port,
        database=str(database),
    )


engine = create_engine(
    create_db_url(),
    pool_size=CONFIG.database.pool_size,
    max_overflow=CONFIG.database.max_overflow,
    pool_timeout=CONFIG.database.pool_timeout,
    pool_recycle=CONFIG.database.pool_recycle,
    pool_pre_ping=CONFIG.database.pool_pre_ping,
    echo=False,
)

SessionLocal = sessionmaker(
    bind=engine,
    autoflush=False,
    expire_on_commit=False,
)


def get_session() -> Generator[Session, None, None]:
    """Yield one database session for framework-managed request scopes."""
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


@contextmanager
def session_scope() -> Generator[Session, None, None]:
    """Yield one database session for local context-managed usage."""
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


def dispose_engine() -> None:
    """Dispose SQLAlchemy engine and close pooled connections."""
    engine.dispose()
