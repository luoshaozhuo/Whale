"""State-update role for refresh-source-state use case."""

from __future__ import annotations

from whale.ingest.ports.store.source_state_repository_port import (
    SourceStateRepositoryPort,
)
from whale.ingest.usecases.dtos.source_state_data import SourceStateData


class StateUpdateRole:
    """Persist acquired source states into the local state cache."""

    def __init__(
        self,
        store_port: SourceStateRepositoryPort,
    ) -> None:
        """Store the repository dependency used for persistence."""
        self._store_port = store_port

    def apply(self, data: SourceStateData) -> SourceStateData:
        """Persist acquired states and return the updated source-state data."""
        if not data.acquired_states:
            data.updated_count = 0
            return data

        data.updated_count = self._store_port.upsert_many(
            data.source_id,
            data.acquired_states,
        )
        return data
