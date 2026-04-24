"""Unit tests for the SQLite device-variable-state repository."""

from __future__ import annotations

from collections.abc import Generator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from whale.ingest.adapters.store import sqlite_variable_state_repository as repository_module
from whale.ingest.adapters.store.sqlite_variable_state_repository import (
    SqliteVariableStateRepository,
)
from whale.ingest.framework.persistence.base import Base
from whale.ingest.framework.persistence.orm.variable_state_orm import (
    VariableStateORM,
)
from whale.ingest.usecases.dtos.acquired_node_state import AcquiredNodeState


def test_store_many_updates_one_state_row_per_device_model_variable() -> None:
    """Keep one state row per device code, model id and variable key."""
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
        repository = SqliteVariableStateRepository()
        first_observed_at = datetime(2026, 4, 23, 10, 0, tzinfo=UTC)
        second_observed_at = first_observed_at + timedelta(minutes=1)

        processed_first = repository.store_many(
            "goldwind_gw121_opcua",
            [
                AcquiredNodeState(
                    source_id="WTG_01",
                    node_key="TotW",
                    node_id="ns=2;s=WTG_01.TotW",
                    value="1200.0",
                    observed_at=first_observed_at,
                )
            ],
        )
        processed_second = repository.store_many(
            "goldwind_gw121_opcua",
            [
                AcquiredNodeState(
                    source_id="WTG_01",
                    node_key="TotW",
                    node_id="ns=2;s=WTG_01.TotW",
                    value="1250.0",
                    observed_at=second_observed_at,
                )
            ],
        )

        rows = list(
            session.scalars(
                select(VariableStateORM).order_by(
                    VariableStateORM.device_code,
                    VariableStateORM.model_id,
                    VariableStateORM.variable_key,
                )
            )
        )

        assert processed_first == 1
        assert processed_second == 1
        assert len(rows) == 1
        assert rows[0].device_code == "WTG_01"
        assert rows[0].model_id == "goldwind_gw121_opcua"
        assert rows[0].variable_key == "TotW"
        assert rows[0].value == "1250.0"
        assert rows[0].source_observed_at == second_observed_at.replace(tzinfo=None)
        assert rows[0].received_at <= rows[0].updated_at
    finally:
        repository_module.session_scope = original_session_scope
        session.close()
        engine.dispose()
