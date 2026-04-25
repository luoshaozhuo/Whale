"""SQLite-backed latest-state cache for ingest."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.dialects.sqlite import insert

from whale.ingest.framework.persistence.orm.variable_state_orm import (
    VariableStateORM,
)
from whale.ingest.framework.persistence.session import session_scope
from whale.ingest.ports.state import (
    SourceStateCachePort,
    SourceStateSnapshotReaderPort,
)
from whale.ingest.usecases.dtos.acquired_node_state import AcquiredNodeState
from whale.ingest.usecases.dtos.cached_source_state import CachedSourceState


class SqliteSourceStateCache(SourceStateCachePort, SourceStateSnapshotReaderPort):
    """Persist and read the local latest-state cache from SQLite."""

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
            statement = insert(VariableStateORM).values(rows)
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
                    select(VariableStateORM).order_by(
                        VariableStateORM.device_code,
                        VariableStateORM.model_id,
                        VariableStateORM.variable_key,
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
