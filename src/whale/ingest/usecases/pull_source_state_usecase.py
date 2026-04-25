"""Pull-source-state use case for ingest."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime

from whale.ingest.ports.source.source_acquisition_definition_port import (
    SourceAcquisitionDefinitionPort,
)
from whale.ingest.ports.source.source_acquisition_port_registry import (
    SourceAcquisitionPortRegistry,
)
from whale.ingest.ports.store.source_state_store_port import (
    SourceStateStorePort,
)
from whale.ingest.usecases.dtos.acquisition_status import AcquisitionStatus
from whale.ingest.usecases.dtos.pull_source_state_result import (
    PullSourceStateResult,
)
from whale.ingest.usecases.dtos.source_runtime_config_data import (
    SourceRuntimeConfigData,
)
from whale.ingest.usecases.roles.pull_role import PullRole
from whale.ingest.usecases.roles.state_update_role import StateUpdateRole


class PullSourceStateUseCase:
    """Pull source states and update the local cache."""

    def __init__(
        self,
        acquisition_definition_port: SourceAcquisitionDefinitionPort,
        acquisition_port_registry: SourceAcquisitionPortRegistry,
        store_port: SourceStateStorePort,
        max_in_flight: int = 8,
    ) -> None:
        """Store use-case dependencies.

        Args:
            acquisition_definition_port: Port used to build acquisition definitions.
            acquisition_port_registry: Protocol-to-adapter registry used to execute source
                acquisition.
            store_port: Port used to persist acquired source states.
            max_in_flight: Maximum number of source pulls allowed concurrently.
        """
        if max_in_flight <= 0:
            raise ValueError("max_in_flight must be greater than 0")
        self._acquisition_definition_port = acquisition_definition_port
        self._acquisition_port_registry = acquisition_port_registry
        self._update_role = StateUpdateRole(store_port=store_port)
        self._max_in_flight = max_in_flight

    async def execute(
        self,
        runtime_configs: list[SourceRuntimeConfigData],
    ) -> list[PullSourceStateResult]:
        """Execute one batch of runtime configs with bounded device concurrency."""
        if not runtime_configs:
            return []

        semaphore = asyncio.Semaphore(self._max_in_flight)
        tasks = [
            asyncio.create_task(self._execute_runtime_config(runtime_config, semaphore))
            for runtime_config in runtime_configs
        ]
        return list(await asyncio.gather(*tasks))

    async def _execute_runtime_config(
        self,
        runtime_config: SourceRuntimeConfigData,
        semaphore: asyncio.Semaphore,
    ) -> PullSourceStateResult:
        """Execute one pull step for one runtime config."""
        async with semaphore:
            started_at = datetime.now(tz=UTC)
            data = await self._build_pull_role(runtime_config).acquire(runtime_config)
            if data.acquisition_status is AcquisitionStatus.SUCCEEDED:
                await asyncio.to_thread(
                    self._update_role.apply_for_mode,
                    data,
                    runtime_config.acquisition_mode,
                )

            return PullSourceStateResult(
                runtime_config_id=runtime_config.runtime_config_id,
                status=data.acquisition_status,
                started_at=started_at,
                ended_at=datetime.now(tz=UTC),
                error_message=data.last_error,
            )

    def _build_pull_role(self, runtime_config: SourceRuntimeConfigData) -> PullRole:
        """Build one pull role using the adapter registered for the runtime protocol."""
        return PullRole(
            acquisition_definition_port=self._acquisition_definition_port,
            acquisition_port=self._acquisition_port_registry.get(runtime_config.protocol),
        )
