"""Data object for one refresh-source-state execution."""

from __future__ import annotations

from dataclasses import dataclass, field

from whale.ingest.usecases.dtos.acquired_node_state import AcquiredNodeState
from whale.ingest.usecases.dtos.acquisition_status import AcquisitionStatus


@dataclass(slots=True)
class SourceStateData:
    """Carry acquisition and persistence state for one refresh execution."""

    runtime_config_id: int
    source_id: str
    source_name: str
    protocol: str
    acquisition_status: AcquisitionStatus
    acquired_states: list[AcquiredNodeState] = field(default_factory=list)
    received_count: int = 0
    updated_count: int = 0
    last_error: str | None = None
