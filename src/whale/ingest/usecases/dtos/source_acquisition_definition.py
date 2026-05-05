"""Acquisition config DTO for one source runtime config."""

from __future__ import annotations

from dataclasses import dataclass

from whale.ingest.usecases.dtos.acquisition_item_data import AcquisitionItemData
from whale.ingest.usecases.dtos.source_connection_data import SourceConnectionData


@dataclass(slots=True)
class SourceAcquisitionDefinition:
    """Describe the source acquisition config for one runtime config."""

    ld_id: str
    connection: SourceConnectionData
    items: list[AcquisitionItemData]
    request_timeout_ms: int = 5000
    poll_interval_ms: int = 1000
