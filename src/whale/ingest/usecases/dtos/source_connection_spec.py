"""Connection specification DTO for one ingest source."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class SourceConnectionSpec:
    """Connection-facing access specification for one source."""

    source_id: str
    source_name: str
    protocol: str
    endpoint: str
    security_policy: str | None
    security_mode: str | None
    update_interval_ms: int
    enabled: bool
