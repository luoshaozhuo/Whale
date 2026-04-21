"""Counting source-state repository adapter.

This adapter is a temporary store-side implementation used to keep the ingest
main flow runnable before a real persistence-backed repository is introduced.

Behavior:
- does not persist any state
- returns the count of received acquired states
"""

from __future__ import annotations

from whale.ingest.ports.store.source_state_repository_port import (
    SourceStateRepositoryPort,
)


class CountingSourceStateRepositoryAdapter(SourceStateRepositoryPort):
    """Temporary repository adapter that returns the number of input states."""

    def upsert_many(
        self,
        source_id: str,
        acquired_states: list[object],
    ) -> int:
        """Return the number of acquired states as the updated count."""
        del source_id
        return len(acquired_states)