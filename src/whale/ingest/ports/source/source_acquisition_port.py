"""Source acquisition port for ingest."""

from __future__ import annotations

from typing import Protocol

from whale.ingest.usecases.dtos.source_config_data import SourceConfigData


class SourceAcquisitionPort(Protocol):
    """Acquire source states from one configured source."""

    def read_once(self, source_config: SourceConfigData) -> list[object]:
        """Acquire a batch of source states for one source."""

    def subscribe(self, source_config: SourceConfigData) -> None:
        """Start subscription-based acquisition for one source."""
