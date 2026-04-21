"""Minimal source-state repository adapter for ingest."""

from __future__ import annotations

from whale.ingest.ports.store.source_state_repository_port import (
    SourceStateRepositoryPort,
)


class NoOpSourceStateRepositoryAdapter(SourceStateRepositoryPort):
    """Provide the smallest repository implementation for scheduler bootstrap."""

    def upsert_many(
        self,
        source_id: str,
        acquired_states: list[object],
    ) -> int:
        """Return the number of received states without extra persistence."""
        _ = source_id
        return len(acquired_states)
