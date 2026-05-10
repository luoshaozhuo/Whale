# src/whale/ingest/ports/state/source_state_cache_port.py

"""State-cache port for ingest latest-state refresh."""

from __future__ import annotations

from typing import Protocol

from whale.ingest.usecases.dtos.acquired_node_state import AcquiredNodeState


class SourceStateCachePort(Protocol):
    """Update the local latest-state cache only."""

    def update(
        self,
        *,
        ld_name: str,
        states: list[AcquiredNodeState],
    ) -> int:
        """Refresh cached source states for one logical device."""