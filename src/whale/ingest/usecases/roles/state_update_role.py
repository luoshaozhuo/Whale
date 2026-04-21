"""State-update role for maintain-source-state use case."""

from __future__ import annotations

from whale.ingest.ports.store.source_state_repository_port import (
    SourceStateRepositoryPort,
)
from whale.ingest.usecases.dtos.source_state_data import SourceStateData


class StateUpdateRole:
    """Persist acquired source states from shared use-case data."""

    def __init__(
        self,
        data: SourceStateData,
        store_port: SourceStateRepositoryPort,
    ) -> None:
        """Bind the role to source-state data and store port."""
        self._data = data
        self._store_port = store_port

    def apply(self) -> None:
        """Persist acquired states and store the updated count in shared data."""
        if not self._data.acquired_states:
            self._data.updated_count = 0
            return

        self._data.updated_count = self._store_port.upsert_many(
            self._data.source_id,
            self._data.acquired_states,
        )
