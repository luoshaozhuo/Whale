"""Snapshot-reader port for the local latest-state cache."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol


@dataclass(slots=True)
class CachedNodeValue:
    """One cached node value within the LD/source latest-state view."""

    node_key: str
    value: str
    quality: str | None = None
    source_timestamp: datetime | None = None
    server_timestamp: datetime | None = None
    client_sequence: int | None = None
    updated_at: datetime | None = None
    attributes: dict[str, object] | None = None


@dataclass(slots=True)
class CachedSourceState:
    """One LD/source latest-state snapshot."""

    ld_name: str
    source_id: str
    availability_status: str
    unavailable_reason: str | None
    batch_observed_at: datetime | None
    client_received_at: datetime | None
    client_processed_at: datetime | None
    last_alive_at: datetime | None
    last_value_updated_at: datetime | None
    state_updated_at: datetime
    values: list[CachedNodeValue]


class SourceStateSnapshotReaderPort(Protocol):
    """Read the current full snapshot from the local latest-state cache."""

    def read_snapshot(self) -> list[CachedSourceState]:
        """Return the current full latest-state snapshot."""
