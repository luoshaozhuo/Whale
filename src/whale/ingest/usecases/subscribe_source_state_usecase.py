"""Subscribe-source-state use case for long-running ingest jobs."""

from __future__ import annotations

from threading import Event

from whale.ingest.ports.source.source_acquisition_definition_port import (
    SourceAcquisitionDefinitionPort,
)
from whale.ingest.ports.source.source_acquisition_port_registry import (
    SourceAcquisitionPortRegistry,
)
from whale.ingest.ports.state import SourceStateCachePort
from whale.ingest.usecases.dtos.source_runtime_config_data import (
    SourceRuntimeConfigData,
)
from whale.ingest.usecases.roles.state_update_role import StateUpdateRole
from whale.ingest.usecases.roles.subscribe_role import SubscribeRole


class SubscribeSourceStateUseCase:
    """Start long-running subscriptions that refresh the local state cache."""

    def __init__(
        self,
        acquisition_definition_port: SourceAcquisitionDefinitionPort,
        acquisition_port_registry: SourceAcquisitionPortRegistry,
        state_cache_port: SourceStateCachePort,
    ) -> None:
        """Build dependencies for one long-running cache-refresh job."""
        self._acquisition_definition_port = acquisition_definition_port
        self._acquisition_port_registry = acquisition_port_registry
        self._update_role = StateUpdateRole(state_cache_port=state_cache_port)

    async def execute(
        self,
        runtime_configs: tuple[SourceRuntimeConfigData, ...],
        stop_event: Event,
    ) -> None:
        """Run subscription acquisition until the stop event is set."""
        if not runtime_configs:
            return

        await self._build_subscribe_role(runtime_configs[0]).subscribe(
            runtime_configs=runtime_configs,
            stop_requested=stop_event.is_set,
        )

    def _build_subscribe_role(
        self,
        runtime_config: SourceRuntimeConfigData,
    ) -> SubscribeRole:
        """Build one subscribe role using the adapter registered for the runtime protocol."""
        return SubscribeRole(
            acquisition_definition_port=self._acquisition_definition_port,
            acquisition_port=self._acquisition_port_registry.get(runtime_config.protocol),
            state_update_role=self._update_role,
        )
