"""State-update role for refreshing the local latest-state cache."""

from __future__ import annotations

from whale.ingest.ports.state import (
    ModeAwareSourceStateCachePort,
    SourceStateCachePort,
)
from whale.ingest.usecases.dtos.source_state_data import SourceStateData


class StateUpdateRole:
    """Refresh acquired source states through the configured local cache."""

    def __init__(
        self,
        state_cache_port: SourceStateCachePort,
    ) -> None:
        """Store the cache dependency used for latest-state refresh."""
        self._state_cache_port = state_cache_port

    def apply(self, data: SourceStateData) -> int:
        """Store acquired states and return the processed row count."""
        return self.apply_for_mode(data)

    def apply_for_mode(
        self,
        data: SourceStateData,
        acquisition_mode: str | None = None,
    ) -> int:
        """Store acquired states and optionally pass acquisition-mode metadata."""
        if not data.acquired_states:
            return 0
        if data.model_id is None:
            raise ValueError("model_id is required when storing acquired states")
        if acquisition_mode is not None and isinstance(
            self._state_cache_port, ModeAwareSourceStateCachePort
        ):
            return self._state_cache_port.store_many_for_mode(
                acquisition_mode,
                data.model_id,
                data.acquired_states,
            )
        return self._state_cache_port.store_many(
            data.model_id,
            data.acquired_states,
        )
