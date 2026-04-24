"""Source-state store port for ingest."""

from __future__ import annotations

from typing import Protocol

from whale.ingest.usecases.dtos.acquired_node_state import AcquiredNodeState


class SourceStateStorePort(Protocol):
    """Store acquired source states for downstream consumers.

    Implementations may persist to a latest-state cache, publish to a stream,
    or write to a terminal sink.
    """

    def store_many(
        self,
        model_id: str,
        acquired_states: list[AcquiredNodeState],
    ) -> int:
        """Store many acquired source states and return processed row count.

        Returns:
            Number of state rows accepted by the store.
        """
