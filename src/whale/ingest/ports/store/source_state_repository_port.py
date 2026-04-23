"""Source-state repository port for ingest."""

from __future__ import annotations

from typing import Protocol

from whale.ingest.usecases.dtos.acquired_node_state import AcquiredNodeState


class SourceStateRepositoryPort(Protocol):
    """Persist acquired source states into the local state cache.

    The interface keeps the `upsert_many` name because the application layer
    treats this storage as a latest-state cache keyed by source and node.
    """

    def upsert_many(
        self,
        source_id: str,
        acquired_states: list[AcquiredNodeState],
    ) -> int:
        """Upsert many acquired source states and return processed row count.

        Returns:
            Number of latest-state rows processed by the cache write.
        """
