"""Subscribe role for long-running source acquisition."""

from __future__ import annotations

from collections.abc import Callable

from whale.ingest.ports.source.source_acquisition_definition_port import (
    SourceAcquisitionDefinitionPort,
)
from whale.ingest.ports.source.source_acquisition_port import SourceAcquisitionPort
from whale.ingest.usecases.dtos.source_acquisition_definition import (
    SourceAcquisitionDefinition,
)
from whale.ingest.usecases.dtos.source_runtime_config_data import (
    SourceRuntimeConfigData,
)
from whale.ingest.usecases.dtos.source_subscription_request import (
    SourceSubscriptionRequest,
)


class SubscribeRole:
    """Build subscription requests for runtime-config snapshots."""

    def __init__(
        self,
        acquisition_definition_port: SourceAcquisitionDefinitionPort,
        acquisition_port: SourceAcquisitionPort,
    ) -> None:
        """Store dependencies required for subscription startup."""
        self._acquisition_definition_port = acquisition_definition_port
        self._acquisition_port = acquisition_port

    async def subscribe(
        self,
        runtime_configs: tuple[SourceRuntimeConfigData, ...],
        stop_requested: Callable[[], bool],
    ) -> None:
        """Start merged subscription acquisition until stopped or failed."""
        for runtime_config in runtime_configs:
            if stop_requested():
                return
            config = self._acquisition_definition_port.get_config(runtime_config)
            await self._acquisition_port.subscribe(
                self._build_request(
                    runtime_config,
                    config,
                    stop_requested=stop_requested,
                )
            )

    @staticmethod
    def _build_request(
        runtime_config: SourceRuntimeConfigData,
        config: SourceAcquisitionDefinition,
        *,
        stop_requested: Callable[[], bool],
    ) -> SourceSubscriptionRequest:
        """Build one subscription request from source config data."""
        return SourceSubscriptionRequest(
            source_id=runtime_config.source_id,
            connection=config.connection,
            items=list(config.items),
            stop_requested=stop_requested,
        )
