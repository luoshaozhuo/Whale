"""Minimal OPC UA acquisition adapter for ingest."""

from __future__ import annotations

from whale.ingest.ports.source.source_acquisition_port import SourceAcquisitionPort
from whale.ingest.usecases.dtos.source_config_data import SourceConfigData


class OpcUaSourceAcquisitionAdapter(SourceAcquisitionPort):
    """Provide the minimal acquisition interface for future OPC UA support."""

    def read_once(self, source_config: SourceConfigData) -> list[object]:
        """Return one acquisition batch for the configured source."""
        _ = source_config
        return []

    def subscribe(self, source_config: SourceConfigData) -> None:
        """Start subscription-based acquisition for the configured source."""
        _ = source_config
        raise NotImplementedError("OPC UA subscription is not implemented yet.")
