"""Runtime job model for ingest scheduler."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from threading import Event

from whale.ingest.runtime.job_status import JobStatus
from whale.ingest.usecases.dtos.source_runtime_config_data import (
    SourceRuntimeConfigData,
)
from whale.ingest.usecases.dtos.source_state_acquisition_result import (
    SourceStateAcquisitionResult,
)


@dataclass(slots=True)
class ScheduledSourceJob:
    """In-memory runtime state for one scheduled source job."""

    aps_job_id: str
    status: JobStatus
    runtime_configs: tuple[SourceRuntimeConfigData, ...]
    last_result: SourceStateAcquisitionResult | None = None
    last_results: list[SourceStateAcquisitionResult] | None = None
    last_run_at: datetime | None = None
    next_run_at: datetime | None = None
    stop_event: Event | None = None
