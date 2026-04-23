"""Source acquisition-definition port for ingest."""

from __future__ import annotations

from typing import Protocol

from whale.ingest.usecases.dtos.source_acquisition_definition import (
    SourceAcquisitionDefinition,
)


class SourceAcquisitionDefinitionPort(Protocol):
    """Load the acquisition definition needed for one runtime config."""

    def get_read_once_definition(
        self,
        runtime_config_id: int,
    ) -> SourceAcquisitionDefinition:
        """Return one read-once acquisition definition or raise when missing."""
