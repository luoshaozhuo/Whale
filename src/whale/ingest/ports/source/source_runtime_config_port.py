"""Source runtime configuration port for ingest."""

from __future__ import annotations

from typing import Protocol

from whale.ingest.usecases.dtos.source_runtime_config_data import (
    SourceRuntimeConfigData,
)


class SourceRuntimeConfigPort(Protocol):
    """Load runtime scheduling configuration for enabled sources."""

    def get_enabled_sources(self) -> list[SourceRuntimeConfigData]:
        """Return enabled source runtime configurations."""
