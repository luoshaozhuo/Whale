"""Data object for maintain-source-state use case."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class SourceStateData:
    """Shared data for one source-state maintenance execution."""

    source_id: str
    source_name: str = ""
    protocol: str = ""
    endpoint: str = ""
    security_policy: str | None = None
    security_mode: str | None = None
    update_interval_ms: int = 0
    enabled: bool = False
    acquired_states: list[object] = field(default_factory=list)
    received_count: int = 0
    updated_count: int = 0
    acquisition_status: str = "PENDING"
    last_error: str | None = None
