"""Unit tests for the acquisition role."""

from __future__ import annotations

import asyncio
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
from whale.ingest.usecases.roles.pull_role import PullRole


class FakeAcquisitionDefinitionPort:
    """Fake acquisition-definition port for role tests."""

    def __init__(self, definition: SourceAcquisitionDefinition | None) -> None:
        """Store the definition returned by the fake."""
        self._definition = definition

    def get_config(
        self,
        runtime_config: SourceRuntimeConfigData,
    ) -> SourceAcquisitionDefinition:
        """Return acquisition config for the matching runtime config."""
        if self._definition is None:
            raise LookupError(f"Definition for `{runtime_config.runtime_config_id}` was not found.")
        return self._definition


class FakeSourceAcquisitionPort:
    """Fake source-acquisition port for role tests."""

    def __init__(self, states: list[AcquiredNodeState], error: Exception | None = None) -> None:
        """Store the configured acquisition behavior."""
        self._states = list(states)
        self._error = error
        self.requests: list[SourceAcquisitionRequest] = []

    async def read(self, request: SourceAcquisitionRequest) -> list[AcquiredNodeState]:
        """Capture the request and return the configured response."""
        self.requests.append(request)
        if self._error is not None:
            raise self._error
        return list(self._states)

    async def subscribe(self, request: object) -> None:
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
        model_id="goldwind_gw121_opcua",
        connection=SourceConnectionData(
            endpoint="opc.tcp://127.0.0.1:4840",
            params={
                "security_policy": "None",
                "security_mode": "None",
                "namespace_uri": "urn:windfarm:2wtg",
            },
        ),
        items=[
            AcquisitionItemData(
                key="TotW",
                locator="nsu=urn:windfarm:2wtg;s=WTG_01.TotW",
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
            value="1200.0",
            observed_at=datetime.now(tz=UTC),
        )
    ]


def test_acquire_builds_state_data_from_ports_and_adapter() -> None:
    """Coordinate both query ports and the acquisition port into source-state data."""
    runtime_config = _build_runtime_config()
    acquisition_port = FakeSourceAcquisitionPort(_build_states())
    role = PullRole(
        acquisition_definition_port=FakeAcquisitionDefinitionPort(_build_definition()),
        acquisition_port=acquisition_port,
    )

    data = asyncio.run(role.acquire(runtime_config))

    assert data.runtime_config_id == 101
    assert data.model_id == "goldwind_gw121_opcua"
    assert data.acquisition_status == "SUCCEEDED"
    assert len(data.acquired_states) == 1
    assert data.acquired_states[0].source_id == "WTG_01"
    assert len(acquisition_port.requests) == 1
    assert acquisition_port.requests[0].items[0].locator.endswith("WTG_01.TotW")


def test_acquire_returns_failed_and_last_error_when_adapter_raises() -> None:
    """Capture acquisition exceptions as FAILED state instead of raising."""
    runtime_config = _build_runtime_config()
    role = PullRole(
        acquisition_definition_port=FakeAcquisitionDefinitionPort(_build_definition()),
        acquisition_port=FakeSourceAcquisitionPort([], error=TimeoutError("timeout")),
    )

    data = asyncio.run(role.acquire(runtime_config))

    assert data.acquisition_status == "FAILED"
    assert data.model_id == "goldwind_gw121_opcua"
    assert data.last_error == "timeout"
    assert data.acquired_states == []


def test_acquire_returns_empty_when_no_states_are_received() -> None:
    """Return EMPTY when the adapter returns an empty state list."""
    runtime_config = _build_runtime_config()
    role = PullRole(
        acquisition_definition_port=FakeAcquisitionDefinitionPort(_build_definition()),
        acquisition_port=FakeSourceAcquisitionPort([]),
    )

    data = asyncio.run(role.acquire(runtime_config))

    assert data.acquisition_status == "EMPTY"
    assert data.model_id == "goldwind_gw121_opcua"
    assert data.acquired_states == []
    assert data.last_error is None
