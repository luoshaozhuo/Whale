"""Source runtime-configuration port for ingest."""

from __future__ import annotations

from typing import Protocol

from whale.ingest.usecases.dtos.source_runtime_config_data import (
    SourceRuntimeConfigData,
)


class SourceRuntimeConfigPort(Protocol):
    """Load runtime scheduling configuration for ingest sources."""

    def list_enabled(self) -> list[SourceRuntimeConfigData]:
        """Return enabled runtime configurations."""

    def get_by_id(self, runtime_config_id: int) -> SourceRuntimeConfigData:
        """Return one runtime configuration or raise when it does not exist."""
