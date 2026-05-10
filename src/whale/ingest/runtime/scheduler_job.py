"""Runtime job model for ingest scheduler."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from threading import Event

from whale.ingest.ports.runtime.source_runtime_config_port import (
    SourceRuntimeConfigData,
)
from whale.ingest.runtime.job_status import JobStatus


class AcquisitionStatus(StrEnum):
    """Represent the business status of one refresh acquisition step."""

    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    EMPTY = "EMPTY"
    DISABLED = "DISABLED"


@dataclass(slots=True)
class SourceStateAcquisitionResult:
    """Expose the business outcome of one source acquisition execution."""

    plan_id: str
    task_id: int
    ld_instance_id: int
    status: AcquisitionStatus
    started_at: datetime
    ended_at: datetime
    elapsed_ms: float | None = None
    failure_category: str | None = None
    error_code: str | None = None
    error_message: str | None = None
    expected_item_count: int = 0
    actual_item_count: int = 0
    bad_item_count: int = 0


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
