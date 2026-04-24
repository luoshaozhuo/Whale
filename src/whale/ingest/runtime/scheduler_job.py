"""Runtime job model for ingest scheduler."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from threading import Event

from whale.ingest.runtime.job_status import JobStatus
from whale.ingest.usecases.dtos.pull_source_state_result import (
    PullSourceStateResult,
)
from whale.ingest.usecases.dtos.source_runtime_config_data import (
    SourceRuntimeConfigData,
)


@dataclass(slots=True)
class ScheduledSourceJob:
    """In-memory runtime state for one scheduled source job."""

    aps_job_id: str
    status: JobStatus
    runtime_configs: tuple[SourceRuntimeConfigData, ...]
    last_result: PullSourceStateResult | None = None
    last_results: list[PullSourceStateResult] | None = None
    last_run_at: datetime | None = None
    next_run_at: datetime | None = None
    stop_event: Event | None = None
