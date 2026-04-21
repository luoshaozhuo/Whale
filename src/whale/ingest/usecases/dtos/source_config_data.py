"""Configuration DTO for one ingest source."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class SourceConfigData:
    """Application-facing configuration for one ingest source."""

    source_id: str
    source_name: str
    protocol: str
    endpoint: str
    security_policy: str | None
    security_mode: str | None
    update_interval_ms: int
    enabled: bool
