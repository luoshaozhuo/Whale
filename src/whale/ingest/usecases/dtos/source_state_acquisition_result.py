"""SourceStateAcquisitionResult DTO — 单次采集执行结果."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from whale.ingest.usecases.dtos.acquisition_status import AcquisitionStatus


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
