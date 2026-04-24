"""Data object for one pull-source-state execution."""

from __future__ import annotations

from dataclasses import dataclass, field

from whale.ingest.usecases.dtos.acquired_node_state import AcquiredNodeState
from whale.ingest.usecases.dtos.acquisition_status import AcquisitionStatus


@dataclass(slots=True)
class SourceStateData:
    """Carry acquired source states for one pull execution."""

    runtime_config_id: int
    acquisition_status: AcquisitionStatus
    model_id: str | None = None
    acquired_states: list[AcquiredNodeState] = field(default_factory=list)
    last_error: str | None = None
