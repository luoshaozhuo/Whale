"""Refresh-source-state use case for ingest."""

from __future__ import annotations

from whale.ingest.ports.runtime.source_runtime_config_port import SourceRuntimeConfigPort
from whale.ingest.ports.source.source_acquisition_definition_port import (
    SourceAcquisitionDefinitionPort,
)
from whale.ingest.ports.source.source_acquisition_port import SourceAcquisitionPort
from whale.ingest.ports.store.source_state_repository_port import (
    SourceStateRepositoryPort,
)
from whale.ingest.usecases.dtos.acquisition_status import AcquisitionStatus
from whale.ingest.usecases.dtos.refresh_source_state_command import (
    RefreshSourceStateCommand,
)
from whale.ingest.usecases.dtos.refresh_source_state_result import (
    RefreshSourceStateResult,
)
from whale.ingest.usecases.roles.acquisition_role import AcquisitionRole
from whale.ingest.usecases.roles.state_update_role import StateUpdateRole


class RefreshSourceStateUseCase:
    """Refresh cached source state for one runtime configuration."""

    def __init__(
        self,
        runtime_config_port: SourceRuntimeConfigPort,
        acquisition_definition_port: SourceAcquisitionDefinitionPort,
        acquisition_port: SourceAcquisitionPort,
        store_port: SourceStateRepositoryPort,
    ) -> None:
        """Store use-case dependencies.

        Args:
            runtime_config_port: Port used to query runtime scheduling config.
            acquisition_definition_port: Port used to build acquisition definitions.
            acquisition_port: Port used to execute source acquisition.
            store_port: Port used to persist acquired source states.
        """
        self._runtime_config_port = runtime_config_port
        self._acquisition_definition_port = acquisition_definition_port
        self._acquisition_port = acquisition_port
        self._store_port = store_port

    def execute(
        self,
        command: RefreshSourceStateCommand,
    ) -> RefreshSourceStateResult:
        """Execute one runtime-config-driven source refresh."""
        acquisition_role = AcquisitionRole(
            runtime_config_port=self._runtime_config_port,
            acquisition_definition_port=self._acquisition_definition_port,
            acquisition_port=self._acquisition_port,
        )
        update_role = StateUpdateRole(store_port=self._store_port)

        data = acquisition_role.acquire(command.runtime_config_id)
        if self._should_persist(data.acquisition_status):
            data = update_role.apply(data)

        return RefreshSourceStateResult(
            runtime_config_id=data.runtime_config_id,
            source_id=data.source_id,
            status=data.acquisition_status,
            received_count=data.received_count,
            updated_count=data.updated_count,
            error_message=data.last_error,
        )

    @staticmethod
    def _should_persist(status: AcquisitionStatus) -> bool:
        """Return whether one acquisition status should enter persistence."""
        return status is AcquisitionStatus.SUCCEEDED
