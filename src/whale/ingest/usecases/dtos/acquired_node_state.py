"""Acquired node-state DTO for one ingest source."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(slots=True)
class AcquiredNodeState:
    """Represent one node value collected from one source endpoint."""

    source_id: str
    node_key: str
    value: str
    observed_at: datetime
