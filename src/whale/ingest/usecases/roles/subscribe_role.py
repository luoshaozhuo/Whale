"""Subscribe role for long-running source acquisition."""

from __future__ import annotations

import asyncio
from collections.abc import Callable

from whale.ingest.ports.source.source_acquisition_definition_port import (
    SourceAcquisitionDefinitionPort,
)
from whale.ingest.ports.source.source_acquisition_port import SourceAcquisitionPort
from whale.ingest.usecases.dtos.acquired_node_state import AcquiredNodeState
from whale.ingest.usecases.dtos.acquisition_status import AcquisitionStatus
from whale.ingest.usecases.dtos.source_acquisition_definition import (
    SourceAcquisitionDefinition,
)
from whale.ingest.usecases.dtos.source_runtime_config_data import (
    SourceRuntimeConfigData,
)
from whale.ingest.usecases.dtos.source_state_data import SourceStateData
from whale.ingest.usecases.dtos.source_subscription_request import (
    SourceSubscriptionRequest,
    SubscriptionStateHandler,
)
from whale.ingest.usecases.roles.state_update_role import StateUpdateRole


class SubscribeRole:
    """Build subscription requests for runtime-config snapshots."""

    def __init__(
        self,
        acquisition_definition_port: SourceAcquisitionDefinitionPort,
        acquisition_port: SourceAcquisitionPort,
        state_update_role: StateUpdateRole,
    ) -> None:
        """Store dependencies required for subscription startup."""
        self._acquisition_definition_port = acquisition_definition_port
        self._acquisition_port = acquisition_port
        self._state_update_role = state_update_role

    async def subscribe(
        self,
        runtime_configs: tuple[SourceRuntimeConfigData, ...],
        stop_requested: Callable[[], bool],
    ) -> None:
        """Start merged subscription acquisition until stopped or failed."""
        requests: list[SourceSubscriptionRequest] = []
        for runtime_config in runtime_configs:
            if stop_requested():
                return
            config = self._acquisition_definition_port.get_config(runtime_config)
            requests.append(
                self._build_request(
                    runtime_config,
                    config,
                    stop_requested=stop_requested,
                    state_received=self._build_state_received_handler(runtime_config, config),
                )
            )

        async with asyncio.TaskGroup() as task_group:
            for request in requests:
                task_group.create_task(self._subscribe_request(request))

    @staticmethod
    def _build_request(
        runtime_config: SourceRuntimeConfigData,
        config: SourceAcquisitionDefinition,
        *,
        stop_requested: Callable[[], bool],
        state_received: SubscriptionStateHandler,
    ) -> SourceSubscriptionRequest:
        """Build one subscription request from source config data."""
        return SourceSubscriptionRequest(
            source_id=runtime_config.source_id,
            connection=config.connection,
            items=list(config.items),
            stop_requested=stop_requested,
            state_received=state_received,
        )

    def _build_state_received_handler(
        self,
        runtime_config: SourceRuntimeConfigData,
        config: SourceAcquisitionDefinition,
    ) -> SubscriptionStateHandler:
        """Build one persistence callback for subscription updates."""

        async def _state_received(acquired_states: list[AcquiredNodeState]) -> None:
            await asyncio.to_thread(
                self._state_update_role.apply_for_mode,
                SourceStateData(
                    runtime_config_id=runtime_config.runtime_config_id,
                    acquisition_status=AcquisitionStatus.SUCCEEDED,
                    model_id=config.model_id,
                    acquired_states=acquired_states,
                ),
                runtime_config.acquisition_mode,
            )

        return _state_received

    async def _subscribe_request(self, request: SourceSubscriptionRequest) -> None:
        """Run one subscription request through the configured acquisition port."""
        await self._acquisition_port.subscribe(request)
