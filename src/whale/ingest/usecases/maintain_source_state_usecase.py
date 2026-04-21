"""Maintain-source-state use case for ingest.

This is one of the top-level ingest use cases. At the current stage it only
implements the smallest single-step execution for state maintenance.

Later differences between subscription, polling, and batch-read acquisition
should be extended through ports and adapters without changing the top-level
business boundary of this use case.
"""

from __future__ import annotations

from whale.ingest.ports.source.source_acquisition_port import SourceAcquisitionPort
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
        acquisition_port: SourceAcquisitionPort,
        store_port: SourceStateRepositoryPort,
    ) -> None:
        """Initialize the use case with acquisition and persistence ports.

        Args:
            acquisition_port: Port used to fetch source states from one source.
            store_port: Port used to persist the fetched states as source state.
        """
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
        data = self._build_source_state_data(command)
        acquisition_role = AcquisitionRole(data, self._acquisition_port)
        update_role = StateUpdateRole(data, self._store_port)
        acquisition_role.acquire()
        update_role.apply()
        return MaintainSourceStateResult(
            source_id=data.source_id,
            received_count=data.received_count,
            updated_count=data.updated_count,
        )

    def _build_source_state_data(
        self,
        command: MaintainSourceStateCommand,
    ) -> SourceStateData:
        """Build one source-state data object from an execution plan."""
        plan = command.execution_plan
        return SourceStateData(
            source_id=plan.connection.source_id,
            source_name=plan.connection.source_name,
            protocol=plan.connection.protocol,
            endpoint=plan.connection.endpoint,
            security_policy=plan.connection.security_policy,
            security_mode=plan.connection.security_mode,
            update_interval_ms=plan.connection.update_interval_ms,
            enabled=plan.connection.enabled and plan.schedule.enabled,
            acquisition_status="READY",
        )
