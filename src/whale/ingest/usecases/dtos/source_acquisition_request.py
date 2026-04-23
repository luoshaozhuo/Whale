"""Acquisition request DTO for one read-once source execution."""

from __future__ import annotations

from dataclasses import dataclass

from whale.ingest.usecases.dtos.acquisition_item_data import AcquisitionItemData
from whale.ingest.usecases.dtos.source_connection_data import SourceConnectionData


@dataclass(slots=True)
class SourceAcquisitionRequest:
    """Carry the concrete request payload needed by one acquisition adapter."""

    runtime_config_id: int
    source_id: str
    source_name: str
    protocol: str
    connection: SourceConnectionData
    items: list[AcquisitionItemData]
