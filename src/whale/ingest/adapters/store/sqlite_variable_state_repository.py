"""SQLite-backed variable-state repository for ingest."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy.dialects.sqlite import insert

from whale.ingest.framework.persistence.orm.variable_state_orm import (
    VariableStateORM,
)
from whale.ingest.framework.persistence.session import session_scope
from whale.ingest.ports.store.source_state_store_port import (
    SourceStateStorePort,
)
from whale.ingest.usecases.dtos.acquired_node_state import AcquiredNodeState


class SqliteVariableStateRepository(SourceStateStorePort):
    """Persist acquired states into the latest device-variable state cache."""

    def store_many(
        self,
        model_id: str,
        acquired_states: list[AcquiredNodeState],
    ) -> int:
        """Upsert the provided acquired states and return processed row count.

        Args:
            model_id: Business acquisition-model identifier for the acquired observations.
            acquired_states: Latest-state rows to insert or update.

        Returns:
            Number of latest-state rows processed by the SQLite upsert
            statement.
        """
        received_at = datetime.now(tz=UTC)
        rows = [
            {
                "device_code": state.source_id,
                "model_id": model_id,
                "variable_key": state.node_key,
                "node_id": state.node_id,
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
                    "node_id": statement.excluded.node_id,
                    "value": statement.excluded.value,
                    "source_observed_at": statement.excluded.source_observed_at,
                    "received_at": statement.excluded.received_at,
                    "updated_at": statement.excluded.updated_at,
                },
            )
            session.execute(upsert_statement)
            session.commit()

        return len(rows)
