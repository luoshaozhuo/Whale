"""Runtime job model for ingest scheduler."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from whale.ingest.runtime.acquisition_mode import AcquisitionMode
from whale.ingest.runtime.job_status import JobStatus


@dataclass(slots=True)
class ScheduledSourceJob:
    """In-memory runtime state for one scheduled source job."""

    source_id: str
    mode: AcquisitionMode
    aps_job_id: str
    status: JobStatus
    interval_ms: int | None = None
    last_run_at: datetime | None = None
    next_run_at: datetime | None = None
