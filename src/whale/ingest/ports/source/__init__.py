"""Source-side ports for ingest."""

from whale.ingest.ports.source.source_acquisition_definition_port import (
    SourceAcquisitionDefinitionPort,
)
from whale.ingest.ports.source.source_acquisition_port import SourceAcquisitionPort
from whale.ingest.ports.source.source_acquisition_port_registry import (
    SourceAcquisitionPortRegistry,
)

__all__ = [
    "SourceAcquisitionDefinitionPort",
    "SourceAcquisitionPort",
    "SourceAcquisitionPortRegistry",
]
