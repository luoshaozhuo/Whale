"""Source configuration port for ingest."""

from __future__ import annotations

from typing import Protocol

from whale.ingest.usecases.dtos.source_config_data import SourceConfigData


class SourceConfigPort(Protocol):
    """Load source configuration for one ingest source."""

    def get_source_config(self, source_id: str) -> SourceConfigData | None:
        """Return source configuration for one source identifier."""
