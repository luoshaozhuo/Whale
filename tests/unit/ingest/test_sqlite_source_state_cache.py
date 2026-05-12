"""Unit tests for the SQLite-backed latest-state cache."""

from __future__ import annotations

from collections.abc import Generator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from whale.ingest.adapters.state import sqlite_source_state_cache as cache_module
from whale.ingest.adapters.state.sqlite_source_state_cache import (
    SqliteSourceStateCache,
    _CacheBase,
    _LdStateRow,
    _VariableStateRow,
)
from whale.ingest.usecases.dtos.acquired_node_state import (
    AcquiredNodeStateBatch,
    AcquiredNodeValue,
)


def _patch_session_scope() -> tuple[Session, callable]:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    _CacheBase.metadata.create_all(engine)
    session = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)()

    @contextmanager
    def _session_scope() -> Generator[Session, None, None]:
        yield session

    original = cache_module.session_scope
    cache_module.session_scope = _session_scope

    def _restore() -> None:
        cache_module.session_scope = original
        session.close()
        engine.dispose()

    return session, _restore


def _build_batch(
    *,
    observed_at: datetime,
    value: str,
    server_timestamp: datetime | None = None,
) -> AcquiredNodeStateBatch:
    return AcquiredNodeStateBatch(
        source_id="LD_01",
        batch_observed_at=observed_at,
        client_received_at=observed_at,
        client_processed_at=observed_at,
        values=[
            AcquiredNodeValue(
                node_key="TotW",
                value=value,
                quality="Good",
                server_timestamp=server_timestamp,
            )
        ],
    )


def test_update_persists_ld_meta_and_latest_node_value() -> None:
    session, restore = _patch_session_scope()
    try:
        cache = SqliteSourceStateCache()
        first = datetime(2026, 4, 23, 10, 0, tzinfo=UTC)
        second = first + timedelta(minutes=1)

        assert cache.update(
            ld_name="LD_01",
            batch=_build_batch(observed_at=first, value="1200.0", server_timestamp=first),
        ) == 1
        assert cache.update(
            ld_name="LD_01",
            batch=_build_batch(observed_at=second, value="1250.0", server_timestamp=second),
        ) == 1

        ld_state = session.get(_LdStateRow, "LD_01")
        rows = list(session.scalars(select(_VariableStateRow)))

        assert ld_state is not None
        assert ld_state.source_id == "LD_01"
        assert ld_state.availability_status == "VALID"
        assert ld_state.batch_observed_at == second.replace(tzinfo=None)
        assert len(rows) == 1
        assert rows[0].variable_key == "TotW"
        assert rows[0].value == "1250.0"
        assert rows[0].server_timestamp == second.replace(tzinfo=None)
    finally:
        restore()


def test_older_server_timestamp_does_not_overwrite_current_row() -> None:
    session, restore = _patch_session_scope()
    try:
        cache = SqliteSourceStateCache()
        now = datetime(2026, 4, 23, 10, 0, tzinfo=UTC)

        cache.update(
            ld_name="LD_01",
            batch=_build_batch(
                observed_at=now,
                value="1250.0",
                server_timestamp=now + timedelta(seconds=5),
            ),
        )
        updated = cache.update(
            ld_name="LD_01",
            batch=_build_batch(
                observed_at=now + timedelta(seconds=10),
                value="1200.0",
                server_timestamp=now,
            ),
        )

        row = session.scalars(select(_VariableStateRow)).one()
        assert updated == 0
        assert row.value == "1250.0"
    finally:
        restore()


def test_read_snapshot_and_status_transitions_follow_current_ld_shape() -> None:
    session, restore = _patch_session_scope()
    try:
        cache = SqliteSourceStateCache()
        now = datetime(2026, 4, 23, 10, 0, tzinfo=UTC)
        cache.update(
            ld_name="LD_01",
            batch=AcquiredNodeStateBatch(
                source_id="LD_01",
                batch_observed_at=now,
                client_received_at=now,
                client_processed_at=now,
                values=[
                    AcquiredNodeValue(node_key="Spd", value="9.5"),
                    AcquiredNodeValue(node_key="TotW", value="1200.0"),
                ],
            ),
        )
        cache.mark_unavailable(
            ld_name="LD_01",
            status="OFFLINE",
            observed_at=now + timedelta(seconds=5),
            reason="connection lost",
        )
        cache.mark_alive(ld_name="LD_01", observed_at=now + timedelta(seconds=10))

        snapshot = cache.read_snapshot()

        assert len(snapshot) == 1
        assert snapshot[0].ld_name == "LD_01"
        assert snapshot[0].availability_status == "VALID"
        assert snapshot[0].unavailable_reason is None
        assert [value.node_key for value in snapshot[0].values] == ["Spd", "TotW"]

        rows = list(
            session.scalars(
                select(_VariableStateRow).order_by(_VariableStateRow.variable_key)
            )
        )
        assert all(row.availability_status == "OFFLINE" for row in rows)
    finally:
        restore()
