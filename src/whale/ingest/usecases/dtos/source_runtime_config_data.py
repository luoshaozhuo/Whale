"""Runtime scheduling DTO for one ingest source."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class SourceRuntimeConfigData:
    """Scheduler-facing runtime configuration for one source."""

    source_id: str
    protocol: str
    acquisition_mode: str
    interval_ms: int
    enabled: bool
