"""State-update role for the pull-source-state use case."""

from __future__ import annotations

from whale.ingest.ports.store.source_state_store_port import (
    SourceStateStorePort,
)
from whale.ingest.usecases.dtos.source_state_data import SourceStateData


class StateUpdateRole:
    """Store acquired source states through the configured sink."""

    def __init__(
        self,
        store_port: SourceStateStorePort,
    ) -> None:
        """Store the sink dependency used for state updates."""
        self._store_port = store_port

    def apply(self, data: SourceStateData) -> int:
        """Store acquired states and return the processed row count."""
        if not data.acquired_states:
            return 0
        if data.model_id is None:
            raise ValueError("model_id is required when storing acquired states")
        return self._store_port.store_many(
            data.model_id,
            data.acquired_states,
        )
