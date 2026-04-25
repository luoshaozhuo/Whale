"""Snapshot-reader port for the local latest-state cache."""

from __future__ import annotations

from typing import Protocol

from whale.ingest.usecases.dtos.cached_source_state import CachedSourceState


class SourceStateSnapshotReaderPort(Protocol):
    """Read the current full snapshot from the local latest-state cache."""

    def read_snapshot(self) -> list[CachedSourceState]:
        """Return the current full latest-state snapshot."""
