"""Unit tests for the acquisition role."""

from __future__ import annotations

from datetime import UTC, datetime

from whale.ingest.usecases.dtos.acquired_node_state import AcquiredNodeState
from whale.ingest.usecases.dtos.acquisition_item_data import AcquisitionItemData
from whale.ingest.usecases.dtos.source_acquisition_definition import (
    SourceAcquisitionDefinition,
)
from whale.ingest.usecases.dtos.source_acquisition_request import (
    SourceAcquisitionRequest,
)
from whale.ingest.usecases.dtos.source_connection_data import SourceConnectionData
from whale.ingest.usecases.dtos.source_runtime_config_data import (
    SourceRuntimeConfigData,
)
from whale.ingest.usecases.roles.acquisition_role import AcquisitionRole


class FakeRuntimeConfigPort:
    """Fake runtime-config port for role tests."""

    def __init__(self, config: SourceRuntimeConfigData) -> None:
        """Store the runtime config returned by the fake."""
        self._config = config

    def list_enabled(self) -> list[SourceRuntimeConfigData]:
        """Return the enabled config if applicable."""
        if self._config.enabled:
            return [self._config]
        return []

    def get_by_id(self, runtime_config_id: int) -> SourceRuntimeConfigData:
        """Return the configured runtime config or raise when it is missing."""
        if runtime_config_id != self._config.runtime_config_id:
            raise LookupError(f"Runtime config `{runtime_config_id}` was not found.")
        return self._config


class FakeAcquisitionDefinitionPort:
    """Fake acquisition-definition port for role tests."""

    def __init__(self, definition: SourceAcquisitionDefinition | None) -> None:
        """Store the definition returned by the fake."""
        self._definition = definition

    def get_read_once_definition(
        self,
        runtime_config_id: int,
    ) -> SourceAcquisitionDefinition:
        """Return the configured definition or raise when missing."""
        if self._definition is None or self._definition.runtime_config_id != runtime_config_id:
            raise LookupError(f"Definition for `{runtime_config_id}` was not found.")
        return self._definition


class FakeSourceAcquisitionPort:
    """Fake source-acquisition port for role tests."""

    def __init__(self, states: list[AcquiredNodeState], error: Exception | None = None) -> None:
        """Store the configured acquisition behavior."""
        self._states = list(states)
        self._error = error
        self.requests: list[SourceAcquisitionRequest] = []

    def read_once(self, request: SourceAcquisitionRequest) -> list[AcquiredNodeState]:
        """Capture the request and return the configured response."""
        self.requests.append(request)
        if self._error is not None:
            raise self._error
        return list(self._states)

    def subscribe(self, request: object) -> None:
        """Unused subscription hook required by the port contract."""
        del request
        raise NotImplementedError


def _build_runtime_config() -> SourceRuntimeConfigData:
    """Build one runtime config for acquisition-role tests."""
    return SourceRuntimeConfigData(
        runtime_config_id=101,
        source_id="WTG_01",
        protocol="opcua",
        acquisition_mode="ONCE",
        interval_ms=0,
        enabled=True,
    )


def _build_definition() -> SourceAcquisitionDefinition:
    """Build one acquisition definition for acquisition-role tests."""
    return SourceAcquisitionDefinition(
        runtime_config_id=101,
        source_id="WTG_01",
        source_name="WTG_01",
        protocol="opcua",
        connection=SourceConnectionData(
            endpoint="opc.tcp://127.0.0.1:4840",
            security_policy="None",
            security_mode="None",
            update_interval_ms=100,
        ),
        items=[
            AcquisitionItemData(
                key="TotW",
                address="nsu=urn:windfarm:2wtg;s=WTG_01.TotW",
                namespace_uri="urn:windfarm:2wtg",
                display_name="TotW",
            )
        ],
    )


def _build_states() -> list[AcquiredNodeState]:
    """Build one acquired-state list for acquisition-role tests."""
    return [
        AcquiredNodeState(
            source_id="WTG_01",
            node_key="TotW",
            node_id="nsu=urn:windfarm:2wtg;s=WTG_01.TotW",
            value="1200.0",
            quality=None,
            observed_at=datetime.now(tz=UTC),
        )
    ]


def test_acquire_builds_state_data_from_ports_and_adapter() -> None:
    """Coordinate both query ports and the acquisition port into source-state data."""
    acquisition_port = FakeSourceAcquisitionPort(_build_states())
    role = AcquisitionRole(
        runtime_config_port=FakeRuntimeConfigPort(_build_runtime_config()),
        acquisition_definition_port=FakeAcquisitionDefinitionPort(_build_definition()),
        acquisition_port=acquisition_port,
    )

    data = role.acquire(101)

    assert data.runtime_config_id == 101
    assert data.source_id == "WTG_01"
    assert data.acquisition_status == "SUCCEEDED"
    assert data.received_count == 1
    assert len(acquisition_port.requests) == 1
    assert acquisition_port.requests[0].items[0].address.endswith("WTG_01.TotW")


def test_acquire_returns_failed_and_last_error_when_adapter_raises() -> None:
    """Capture acquisition exceptions as FAILED state instead of raising."""
    role = AcquisitionRole(
        runtime_config_port=FakeRuntimeConfigPort(_build_runtime_config()),
        acquisition_definition_port=FakeAcquisitionDefinitionPort(_build_definition()),
        acquisition_port=FakeSourceAcquisitionPort([], error=TimeoutError("timeout")),
    )

    data = role.acquire(101)

    assert data.acquisition_status == "FAILED"
    assert data.last_error == "timeout"
    assert data.received_count == 0


def test_acquire_returns_empty_when_no_states_are_received() -> None:
    """Return EMPTY when the adapter returns an empty state list."""
    role = AcquisitionRole(
        runtime_config_port=FakeRuntimeConfigPort(_build_runtime_config()),
        acquisition_definition_port=FakeAcquisitionDefinitionPort(_build_definition()),
        acquisition_port=FakeSourceAcquisitionPort([]),
    )

    data = role.acquire(101)

    assert data.acquisition_status == "EMPTY"
    assert data.received_count == 0
    assert data.last_error is None
