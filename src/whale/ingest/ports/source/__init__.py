"""Source-side ports for ingest."""

from whale.ingest.ports.source.source_acquisition_definition_port import (
    SourceAcquisitionDefinitionPort,
)
from whale.ingest.ports.source.source_acquisition_port import SourceAcquisitionPort

__all__ = [
    "SourceAcquisitionDefinitionPort",
    "SourceAcquisitionPort",
]
