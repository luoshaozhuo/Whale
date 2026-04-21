"""Maintain-source-state use case for ingest.

This is one of the top-level ingest use cases. At the current stage it only
implements the smallest single-step execution for state maintenance.

Later differences between subscription, polling, and batch-read acquisition
should be extended through ports and adapters without changing the top-level
business boundary of this use case.
"""

from __future__ import annotations

from whale.ingest.ports.source.source_acquisition_port import SourceAcquisitionPort
from whale.ingest.ports.source.source_config_port import SourceConfigPort
from whale.ingest.ports.store.source_state_repository_port import (
    SourceStateRepositoryPort,
)
from whale.ingest.usecases.dtos.maintain_source_state_command import (
    MaintainSourceStateCommand,
)
from whale.ingest.usecases.dtos.maintain_source_state_result import (
    MaintainSourceStateResult,
)
from whale.ingest.usecases.dtos.source_state_data import SourceStateData
from whale.ingest.usecases.roles.acquisition_role import AcquisitionRole
from whale.ingest.usecases.roles.state_update_role import StateUpdateRole


class MaintainSourceStateUseCase:
    """Fetch source states and persist source state updates."""

    def __init__(
        self,
        source_config_port: SourceConfigPort,
        acquisition_port: SourceAcquisitionPort,
        store_port: SourceStateRepositoryPort,
    ) -> None:
        """Initialize the use case with source-side and persistence ports.

        Args:
            source_config_port: Port used to load one source configuration.
            acquisition_port: Port used to fetch source states from one source.
            store_port: Port used to persist the fetched states as source state.
        """
        self._source_config_port = source_config_port
        self._acquisition_port = acquisition_port
        self._store_port = store_port

    def execute(
        self,
        command: MaintainSourceStateCommand,
    ) -> MaintainSourceStateResult:
        """Execute one minimal state-maintenance step for a source.

        Args:
            command: Input identifying the source to process.

        Returns:
            Minimal execution statistics for this step.
        """
        data = SourceStateData(source_id=command.source_id)
        acquisition_role = AcquisitionRole(
            data,
            self._source_config_port,
            self._acquisition_port,
        )
        update_role = StateUpdateRole(data, self._store_port)
        acquisition_role.load_config()
        acquisition_role.acquire()
        update_role.apply()
        return MaintainSourceStateResult(
            source_id=data.source_id,
            received_count=data.received_count,
            updated_count=data.updated_count,
        )
