"""Source-health entity for ingest.

This is a minimal reusable ingest entity. Future iterations may extend it with
fields such as last success time, error message, and recovery state.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class SourceHealthState:
    """Minimal health status for one source."""

    source_id: str
    status: str
