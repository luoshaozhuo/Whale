"""Acquisition role for refresh-source-state use case."""

from __future__ import annotations

from whale.ingest.ports.runtime.source_runtime_config_port import SourceRuntimeConfigPort
from whale.ingest.ports.source.source_acquisition_definition_port import (
    SourceAcquisitionDefinitionPort,
)
from whale.ingest.ports.source.source_acquisition_port import SourceAcquisitionPort
from whale.ingest.usecases.dtos.acquisition_status import AcquisitionStatus
from whale.ingest.usecases.dtos.source_state_data import SourceStateData


class AcquisitionRole:
    """Acquire source states for one runtime-config-driven refresh."""

    def __init__(
        self,
        runtime_config_port: SourceRuntimeConfigPort,
        acquisition_definition_port: SourceAcquisitionDefinitionPort,
        acquisition_port: SourceAcquisitionPort,
    ) -> None:
        """Store dependencies required for one acquisition step."""
        self._runtime_config_port = runtime_config_port
        self._acquisition_definition_port = acquisition_definition_port
        self._acquisition_port = acquisition_port

    def acquire(self, runtime_config_id: int) -> SourceStateData:
        """Acquire source states for one runtime config."""
        try:
            runtime_config = self._runtime_config_port.get_by_id(runtime_config_id)
        except LookupError as exc:
            return SourceStateData(
                runtime_config_id=runtime_config_id,
                source_id="",
                source_name="",
                protocol="",
                acquisition_status=AcquisitionStatus.FAILED,
                last_error=str(exc),
            )

        if not runtime_config.enabled:
            return SourceStateData(
                runtime_config_id=runtime_config.runtime_config_id,
                source_id=runtime_config.source_id,
                source_name=runtime_config.source_id,
                protocol=runtime_config.protocol,
                acquisition_status=AcquisitionStatus.DISABLED,
            )

        try:
            definition = self._acquisition_definition_port.get_read_once_definition(
                runtime_config_id
            )
        except LookupError as exc:
            return SourceStateData(
                runtime_config_id=runtime_config.runtime_config_id,
                source_id=runtime_config.source_id,
                source_name=runtime_config.source_id,
                protocol=runtime_config.protocol,
                acquisition_status=AcquisitionStatus.FAILED,
                last_error=str(exc),
            )

        try:
            states = self._acquisition_port.read_once(definition.to_request())
        except Exception as exc:
            return SourceStateData(
                runtime_config_id=definition.runtime_config_id,
                source_id=definition.source_id,
                source_name=definition.source_name,
                protocol=definition.protocol,
                acquisition_status=AcquisitionStatus.FAILED,
                last_error=str(exc),
            )

        return SourceStateData(
            runtime_config_id=definition.runtime_config_id,
            source_id=definition.source_id,
            source_name=definition.source_name,
            protocol=definition.protocol,
            acquisition_status=(AcquisitionStatus.SUCCEEDED if states else AcquisitionStatus.EMPTY),
            acquired_states=states,
            received_count=len(states),
        )
