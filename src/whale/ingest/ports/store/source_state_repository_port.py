"""Source-state repository port for ingest."""

from __future__ import annotations

from typing import Protocol


class SourceStateRepositoryPort(Protocol):
    """Persist acquired source states into state storage."""

    def upsert_many(
        self,
        source_id: str,
        acquired_states: list[object],
    ) -> int:
        """Persist many acquired source states and return updated count."""
