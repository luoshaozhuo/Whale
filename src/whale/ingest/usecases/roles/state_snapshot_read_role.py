"""State-snapshot read role for ingest."""

from __future__ import annotations

from whale.ingest.ports.state import SourceStateSnapshotReaderPort
from whale.ingest.usecases.dtos.cached_source_state import CachedSourceState


class StateSnapshotReadRole:
    """Read the current full latest-state snapshot from the configured cache."""

    def __init__(self, snapshot_reader_port: SourceStateSnapshotReaderPort) -> None:
        """Store the snapshot-reader dependency."""
        self._snapshot_reader_port = snapshot_reader_port

    def read_snapshot(self) -> list[CachedSourceState]:
        """Return the full latest-state snapshot."""
        return self._snapshot_reader_port.read_snapshot()
