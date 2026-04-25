"""State-cache ports for ingest latest-state refresh."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from whale.ingest.usecases.dtos.acquired_node_state import AcquiredNodeState


class SourceStateCachePort(Protocol):
    """Update the local latest-state cache only.

    Implementations refresh the current state view used by ingest runtime and
    later snapshot emission. They do not publish messages downstream.
    """

    def store_many(
        self,
        model_id: str,
        acquired_states: list[AcquiredNodeState],
    ) -> int:
        """Refresh many cached source states and return processed row count."""


@runtime_checkable
class ModeAwareSourceStateCachePort(SourceStateCachePort, Protocol):
    """Optional cache extension that also records acquisition mode metadata."""

    def store_many_for_mode(
        self,
        acquisition_mode: str,
        model_id: str,
        acquired_states: list[AcquiredNodeState],
    ) -> int:
        """Refresh many cached states tagged with their acquisition mode."""
