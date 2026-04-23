"""Configuration adapters for ingest."""

from whale.ingest.adapters.config.opcua_source_acquisition_definition_repository import (
    OpcUaSourceAcquisitionDefinitionRepository,
)
from whale.ingest.adapters.config.source_runtime_config_repository import (
    SourceRuntimeConfigRepository,
)

__all__ = [
    "OpcUaSourceAcquisitionDefinitionRepository",
    "SourceRuntimeConfigRepository",
]
