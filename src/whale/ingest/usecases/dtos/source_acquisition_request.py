"""Acquisition request DTO for one source read execution."""

from __future__ import annotations

from dataclasses import dataclass

from whale.ingest.usecases.dtos.acquisition_item_data import AcquisitionItemData
from whale.ingest.usecases.dtos.source_connection_data import SourceConnectionData


@dataclass(slots=True)
class SourceAcquisitionRequest:
    """Carry the concrete request payload needed by one acquisition adapter."""

    source_id: str
    connection: SourceConnectionData
    items: list[AcquisitionItemData]
    resolved_endpoint: str | None = None
    resolved_node_ids: list[str] | None = None
    request_timeout_ms: int = 5000
