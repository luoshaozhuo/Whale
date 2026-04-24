"""Subscribe-source-state use case for long-running ingest jobs."""

from __future__ import annotations

from threading import Event

from whale.ingest.ports.source.source_acquisition_definition_port import (
    SourceAcquisitionDefinitionPort,
)
from whale.ingest.ports.source.source_acquisition_port_registry import (
    SourceAcquisitionPortRegistry,
)
from whale.ingest.usecases.dtos.source_runtime_config_data import (
    SourceRuntimeConfigData,
)
from whale.ingest.usecases.roles.subscribe_role import SubscribeRole


class SubscribeSourceStateUseCase:
    """Start long-running subscriptions for runtime configurations."""

    def __init__(
        self,
        acquisition_definition_port: SourceAcquisitionDefinitionPort,
        acquisition_port_registry: SourceAcquisitionPortRegistry,
    ) -> None:
        """Build subscription dependencies for one long-running job."""
        self._acquisition_definition_port = acquisition_definition_port
        self._acquisition_port_registry = acquisition_port_registry

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
        )
