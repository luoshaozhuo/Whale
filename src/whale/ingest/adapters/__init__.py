"""Adapters for the ingest module."""

from whale.ingest.adapters.config import (
    OpcUaSourceAcquisitionDefinitionRepository,
    SourceRuntimeConfigRepository,
)

__all__ = [
    "OpcUaSourceAcquisitionDefinitionRepository",
    "SourceRuntimeConfigRepository",
]
