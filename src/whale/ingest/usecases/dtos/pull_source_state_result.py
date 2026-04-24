"""Result DTO for the pull-source-state use case."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from whale.ingest.usecases.dtos.acquisition_status import AcquisitionStatus


@dataclass(slots=True)
class PullSourceStateResult:
    """Expose the business outcome of one pull execution."""

    runtime_config_id: int
    status: AcquisitionStatus
    started_at: datetime
    ended_at: datetime
    error_message: str | None
