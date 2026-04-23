"""Acquisition definition DTO for one source runtime config."""

from __future__ import annotations

from dataclasses import dataclass

from whale.ingest.usecases.dtos.acquisition_item_data import AcquisitionItemData
from whale.ingest.usecases.dtos.source_acquisition_request import (
    SourceAcquisitionRequest,
)
from whale.ingest.usecases.dtos.source_connection_data import SourceConnectionData


@dataclass(slots=True)
class SourceAcquisitionDefinition:
    """Describe the read-once acquisition setup for one runtime config."""

    runtime_config_id: int
    source_id: str
    source_name: str
    protocol: str
    connection: SourceConnectionData
    items: list[AcquisitionItemData]

    def to_request(self) -> SourceAcquisitionRequest:
        """Convert the definition into one acquisition request."""
        return SourceAcquisitionRequest(
            runtime_config_id=self.runtime_config_id,
            source_id=self.source_id,
            source_name=self.source_name,
            protocol=self.protocol,
            connection=self.connection,
            items=list(self.items),
        )
