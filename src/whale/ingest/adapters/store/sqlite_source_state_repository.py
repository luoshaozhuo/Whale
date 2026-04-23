"""SQLite-backed source-state repository for ingest."""

from __future__ import annotations

from sqlalchemy.dialects.sqlite import insert
from sqlalchemy.sql import func

from whale.ingest.framework.persistence.orm.source_node_latest_state_orm import (
    SourceNodeLatestStateORM,
)
from whale.ingest.framework.persistence.session import session_scope
from whale.ingest.ports.store.source_state_repository_port import (
    SourceStateRepositoryPort,
)
from whale.ingest.usecases.dtos.acquired_node_state import AcquiredNodeState


class SqliteSourceStateRepository(SourceStateRepositoryPort):
    """Persist acquired source states into the ingest SQLite latest-state cache."""

    def upsert_many(
        self,
        source_id: str,
        acquired_states: list[AcquiredNodeState],
    ) -> int:
        """Upsert the provided acquired states and return processed row count.

        Args:
            source_id: Logical source identifier for the acquired observations.
            acquired_states: Latest-state rows to insert or update.

        Returns:
            Number of latest-state rows processed by the SQLite upsert
            statement.
        """
        rows = [
            {
                "source_id": source_id,
                "node_key": state.node_key,
                "node_id": state.node_id,
                "value": state.value,
                "quality": state.quality,
                "observed_at": state.observed_at,
            }
            for state in acquired_states
        ]

        if not rows:
            return 0

        with session_scope() as session:
            statement = insert(SourceNodeLatestStateORM).values(rows)
            upsert_statement = statement.on_conflict_do_update(
                index_elements=["source_id", "node_key"],
                set_={
                    "node_id": statement.excluded.node_id,
                    "value": statement.excluded.value,
                    "quality": statement.excluded.quality,
                    "observed_at": statement.excluded.observed_at,
                    "updated_at": func.now(),
                },
            )
            session.execute(upsert_statement)
            session.commit()

        return len(rows)
