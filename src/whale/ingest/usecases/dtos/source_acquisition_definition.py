"""Acquisition config DTO for one source runtime config."""

from __future__ import annotations

from dataclasses import dataclass

from whale.ingest.usecases.dtos.acquisition_item_data import AcquisitionItemData
from whale.ingest.usecases.dtos.source_connection_data import SourceConnectionData


@dataclass(slots=True)
class SourceAcquisitionDefinition:
    """Describe the source acquisition config for one runtime config."""

    model_id: str
    connection: SourceConnectionData
    items: list[AcquisitionItemData]
