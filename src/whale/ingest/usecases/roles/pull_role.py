"""Pull role for the pull-source-state use case."""

from __future__ import annotations

from whale.ingest.ports.source.source_acquisition_definition_port import (
    SourceAcquisitionDefinitionPort,
)
from whale.ingest.ports.source.source_acquisition_port import SourceAcquisitionPort
from whale.ingest.usecases.dtos.acquisition_status import AcquisitionStatus
from whale.ingest.usecases.dtos.source_acquisition_definition import (
    SourceAcquisitionDefinition,
)
from whale.ingest.usecases.dtos.source_acquisition_request import (
    SourceAcquisitionRequest,
)
from whale.ingest.usecases.dtos.source_runtime_config_data import (
    SourceRuntimeConfigData,
)
from whale.ingest.usecases.dtos.source_state_data import SourceStateData


class PullRole:
    """Build pull requests and acquire source states for one runtime config."""

    def __init__(
        self,
        acquisition_definition_port: SourceAcquisitionDefinitionPort,
        acquisition_port: SourceAcquisitionPort,
    ) -> None:
        """Store dependencies required for one acquisition step."""
        self._acquisition_definition_port = acquisition_definition_port
        self._acquisition_port = acquisition_port

    async def acquire(self, runtime_config: SourceRuntimeConfigData) -> SourceStateData:
        """Acquire source states for one runtime config."""
        try:
            config = self._acquisition_definition_port.get_config(runtime_config)
        except LookupError as exc:
            return SourceStateData(
                runtime_config_id=runtime_config.runtime_config_id,
                acquisition_status=AcquisitionStatus.FAILED,
                last_error=str(exc),
            )

        try:
            states = await self._acquisition_port.read(self._build_request(runtime_config, config))
        except Exception as exc:
            return SourceStateData(
                runtime_config_id=runtime_config.runtime_config_id,
                acquisition_status=AcquisitionStatus.FAILED,
                model_id=config.ld_id,
                last_error=str(exc),
            )

        return SourceStateData(
            runtime_config_id=runtime_config.runtime_config_id,
            acquisition_status=(AcquisitionStatus.SUCCEEDED if states else AcquisitionStatus.EMPTY),
            model_id=config.ld_id,
            acquired_states=states,
        )

    @staticmethod
    def _build_request(
        runtime_config: SourceRuntimeConfigData,
        config: SourceAcquisitionDefinition,
    ) -> SourceAcquisitionRequest:
        """Build one acquisition request with pre-resolved endpoint and node IDs."""
        ns_uri = config.connection.params.get("namespace_uri", "")
        return SourceAcquisitionRequest(
            source_id=runtime_config.source_id,
            connection=config.connection,
            items=list(config.items),
            resolved_endpoint=config.connection.endpoint,
            request_timeout_ms=config.request_timeout_ms,
            resolved_node_ids=[
                f"nsu={ns_uri};s={item.locator}"
                if ns_uri and not item.locator.startswith(("ns=", "nsu="))
                else item.locator
                for item in config.items
            ],
        )
