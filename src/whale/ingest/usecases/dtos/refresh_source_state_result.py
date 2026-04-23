"""Result DTO for the refresh-source-state use case."""

from __future__ import annotations

from dataclasses import dataclass

from whale.ingest.usecases.dtos.acquisition_status import AcquisitionStatus


@dataclass(slots=True)
class RefreshSourceStateResult:
    """Expose the business result of one refresh execution."""

    runtime_config_id: int
    source_id: str
    status: AcquisitionStatus
    received_count: int
    updated_count: int
    error_message: str | None
