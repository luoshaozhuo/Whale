"""Unit tests for the SQLite latest-state repository."""

from __future__ import annotations

from collections.abc import Generator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from whale.ingest.adapters.store import sqlite_source_state_repository as repository_module
from whale.ingest.adapters.store.sqlite_source_state_repository import (
    SqliteSourceStateRepository,
)
from whale.ingest.framework.persistence.base import Base
from whale.ingest.framework.persistence.orm.source_node_latest_state_orm import (
    SourceNodeLatestStateORM,
)
from whale.ingest.usecases.dtos.acquired_node_state import AcquiredNodeState


def test_upsert_many_updates_latest_state_instead_of_appending_rows() -> None:
    """Keep one latest-state row per source and node key."""
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)()

    @contextmanager
    def _session_scope() -> Generator[Session, None, None]:
        try:
            yield session
        finally:
            pass

    original_session_scope = repository_module.session_scope
    repository_module.session_scope = _session_scope
    try:
        repository = SqliteSourceStateRepository()
        first_observed_at = datetime(2026, 4, 23, 10, 0, tzinfo=UTC)
        second_observed_at = first_observed_at + timedelta(minutes=1)

        processed_first = repository.upsert_many(
            "WTG_01",
            [
                AcquiredNodeState(
                    source_id="WTG_01",
                    node_key="TotW",
                    node_id="ns=2;s=WTG_01.TotW",
                    value="1200.0",
                    quality="GOOD",
                    observed_at=first_observed_at,
                )
            ],
        )
        processed_second = repository.upsert_many(
            "WTG_01",
            [
                AcquiredNodeState(
                    source_id="WTG_01",
                    node_key="TotW",
                    node_id="ns=2;s=WTG_01.TotW",
                    value="1250.0",
                    quality="GOOD",
                    observed_at=second_observed_at,
                )
            ],
        )

        rows = list(
            session.scalars(select(SourceNodeLatestStateORM).order_by(SourceNodeLatestStateORM.id))
        )

        assert processed_first == 1
        assert processed_second == 1
        assert len(rows) == 1
        assert rows[0].source_id == "WTG_01"
        assert rows[0].node_key == "TotW"
        assert rows[0].value == "1250.0"
        assert rows[0].observed_at == second_observed_at.replace(tzinfo=None)
    finally:
        repository_module.session_scope = original_session_scope
        session.close()
        engine.dispose()
