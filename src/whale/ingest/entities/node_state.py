"""Node-state entity for ingest.

This is a minimal reusable ingest entity. Future iterations may extend it with
fields such as quality, source timestamp, staleness, and last receive time.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class NodeState:
    """Minimal state snapshot for one node."""

    node_id: str
    value: object | None = None
