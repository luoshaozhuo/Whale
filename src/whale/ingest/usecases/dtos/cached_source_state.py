"""Latest-state snapshot DTO for one cached source variable."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(slots=True)
class CachedSourceState:
    """Represent one row from the local latest-state cache."""

    id: int
    device_code: str
    model_id: str
    variable_key: str
    value: str | None
    source_observed_at: datetime | None
    received_at: datetime | None
    updated_at: datetime | None
    station_id: str | None = None
    ingested_at: datetime | None = None
    freshness_timeout_ms: int | None = None
    alive_timeout_ms: int | None = None
    acquisition_mode: str | None = None
