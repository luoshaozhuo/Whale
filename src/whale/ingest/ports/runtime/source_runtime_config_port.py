"""Source runtime-configuration port for ingest."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol


@dataclass(slots=True)
class SourceRuntimeConfigData:
    """Scheduler-facing runtime configuration for one source."""

    runtime_config_id: int
    source_id: str
    protocol: str
    acquisition_mode: str
    interval_ms: int
    enabled: bool


@dataclass(slots=True)
class ServerRuntimeConfigData:
    """Describe one simulated server entry resolved from runtime configuration."""

    endpoint_id: int
    ied_name: str
    asset_code: str
    asset_name: str
    ld_name: str
    application_protocol: str
    transport: str
    host: str | None
    port: int | None
    namespace_uri: str | None
    signal_profile_id: int


@dataclass(slots=True)
class SignalProfileItemRuntimeData:
    """Describe one signal item resolved directly from one shared signal profile."""

    signal_profile_id: int
    ln_name: str | None
    do_name: str
    relative_path: str
    data_type: str
    unit: str | None


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
