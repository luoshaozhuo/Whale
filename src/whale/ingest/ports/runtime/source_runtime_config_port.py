"""Source runtime-configuration port for ingest."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol

from whale.ingest.usecases.dtos.source_runtime_config_data import (
    SourceRuntimeConfigData,
)
from whale.ingest.usecases.dtos.server_runtime_config_data import (
    ServerRuntimeConfigData,
)
from whale.ingest.usecases.dtos.signal_profile_item_runtime_data import (
    SignalProfileItemRuntimeData,
)


class SourceRuntimeConfigPort(Protocol):
    """Load runtime scheduling configuration for ingest sources."""

    def list_enabled(self) -> list[SourceRuntimeConfigData]:
        """Return enabled runtime configurations."""

    def list_servers(
        self,
        *,
        group_by: Sequence[str] = (),
        first_group_only: bool = False,
    ) -> list[ServerRuntimeConfigData]:
        """Return server-level runtime configuration rows for source simulation."""

    def list_profile_items(
        self,
        signal_profile_id: int,
    ) -> list[SignalProfileItemRuntimeData]:
        """Return one signal profile's ordered item definitions."""
