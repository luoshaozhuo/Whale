"""Server-level runtime configuration DTO for source simulation."""

from __future__ import annotations

from dataclasses import dataclass


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
