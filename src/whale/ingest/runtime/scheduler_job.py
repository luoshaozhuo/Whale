"""Runtime job model for ingest scheduler."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from whale.ingest.runtime.job_status import JobStatus
from whale.ingest.usecases.dtos.refresh_source_state_result import (
    RefreshSourceStateResult,
)
from whale.ingest.usecases.dtos.source_runtime_config_data import (
    SourceRuntimeConfigData,
)


@dataclass(slots=True)
class ScheduledSourceJob:
    """In-memory runtime state for one scheduled source job."""

    runtime_config: SourceRuntimeConfigData
    aps_job_id: str
    status: JobStatus
    last_result: RefreshSourceStateResult | None = None
    last_run_at: datetime | None = None
    next_run_at: datetime | None = None
