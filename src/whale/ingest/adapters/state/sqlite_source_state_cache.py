"""SQLite-backed latest-state cache for ingest."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import (
    Column,
    DateTime,
    Integer,
    String,
    Text,
    UniqueConstraint,
    select,
)
from sqlalchemy.dialects.sqlite import insert
from sqlalchemy.orm import DeclarativeBase

from whale.ingest.framework.persistence.session import session_scope
from whale.ingest.ports.state.source_state_snapshot_reader_port import (
    CachedSourceState,
    SourceStateSnapshotReaderPort,
)
from whale.ingest.ports.state.source_state_cache_port import SourceStateCachePort
from whale.ingest.usecases.dtos.acquired_node_state import AcquiredNodeState


class _CacheBase(DeclarativeBase):
    """Private declarative base for the variable-state cache table."""


class _VariableStateRow(_CacheBase):
    """Denormalised variable-state row (implementation detail of SqliteSourceStateCache)."""

    __tablename__ = "variable_state"
    __table_args__ = (
        UniqueConstraint("device_code", "model_id", "variable_key",
                         name="uq_variable_state_device_model_variable"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    device_code = Column(String(255), nullable=False)
    model_id = Column(String(255), nullable=False)
    variable_key = Column(String(255), nullable=False)
    value = Column(Text, nullable=False)
    source_observed_at = Column(DateTime(timezone=True), nullable=False)
    received_at = Column(DateTime(timezone=True), nullable=False)
    updated_at = Column(DateTime(timezone=True), nullable=False)


class SqliteSourceStateCache(SourceStateCachePort, SourceStateSnapshotReaderPort):
    """Persist and read the local latest-state cache from SQLite."""

    def __init__(self) -> None:
        """Ensure the variable_state table exists."""
        with session_scope() as session:
            _CacheBase.metadata.create_all(bind=session.get_bind(), checkfirst=True)

    def store_many(
        self,
        model_id: str,
        acquired_states: list[AcquiredNodeState],
    ) -> int:
        """Upsert latest-state rows for the provided acquired states."""
        received_at = datetime.now(tz=UTC)
        rows = [
            {
                "device_code": state.source_id,
                "model_id": model_id,
                "variable_key": state.node_key,
                "value": state.value,
                "source_observed_at": state.observed_at,
                "received_at": received_at,
                "updated_at": received_at,
            }
            for state in acquired_states
        ]

        if not rows:
            return 0

        with session_scope() as session:
            statement = insert(_VariableStateRow).values(rows)
            upsert_statement = statement.on_conflict_do_update(
                index_elements=["device_code", "model_id", "variable_key"],
                set_={
                    "value": statement.excluded.value,
                    "source_observed_at": statement.excluded.source_observed_at,
                    "received_at": statement.excluded.received_at,
                    "updated_at": statement.excluded.updated_at,
                },
            )
            session.execute(upsert_statement)
            session.commit()

        return len(rows)

    def read_snapshot(self) -> list[CachedSourceState]:
        """Return the full current latest-state snapshot from SQLite."""
        with session_scope() as session:
            rows = list(
                session.scalars(
                    select(_VariableStateRow).order_by(
                        _VariableStateRow.device_code,
                        _VariableStateRow.model_id,
                        _VariableStateRow.variable_key,
                    )
                )
            )

        return [
            CachedSourceState(
                id=row.id,
                device_code=row.device_code,
                model_id=row.model_id,
                variable_key=row.variable_key,
                value=row.value,
                source_observed_at=row.source_observed_at,
                received_at=row.received_at,
                updated_at=row.updated_at,
            )
            for row in rows
        ]
