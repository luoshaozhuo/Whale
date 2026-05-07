"""Unit tests for the source-state read role."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime

from whale.ingest.usecases.dtos.acquired_node_state import AcquiredNodeState
from whale.ingest.usecases.dtos.acquisition_item_data import AcquisitionItemData
from whale.ingest.usecases.dtos.source_acquisition_execution_plan import (
    SourceAcquisitionExecutionPlan,
)
from whale.ingest.usecases.dtos.source_acquisition_request import (
    SourceAcquisitionRequest,
)
from whale.ingest.usecases.dtos.source_connection_data import SourceConnectionData
from whale.ingest.usecases.roles.source_state_read_role import SourceStateReadRole


class FakeSourceAcquisitionPort:
    def __init__(self, states: list[AcquiredNodeState], error: Exception | None = None) -> None:
        self._states = list(states)
        self._error = error
        self.requests: list[SourceAcquisitionRequest] = []

    async def read(self, request: SourceAcquisitionRequest) -> list[AcquiredNodeState]:
        self.requests.append(request)
        if self._error is not None:
            raise self._error
        return list(self._states)

    async def subscribe(self, request: object) -> None:
        del request
        raise NotImplementedError


def _build_plan() -> SourceAcquisitionExecutionPlan:
    return SourceAcquisitionExecutionPlan(
        plan_id="plan-1",
        task_id=101,
        ld_instance_id=0,
        acquisition_mode="ONCE",
        protocol="opcua",
        endpoint_config=SourceConnectionData(
            endpoint="opc.tcp://127.0.0.1:4840",
            params={"namespace_uri": "urn:windfarm:2wtg"},
        ),
        request_items=[
            AcquisitionItemData(key="TotW", locator="nsu=urn:windfarm:2wtg;s=WTG_01.TotW"),
        ],
        request_timeout_ms=500,
        freshness_timeout_ms=30000,
        alive_timeout_ms=60000,
    )


def _build_states() -> list[AcquiredNodeState]:
    return [
        AcquiredNodeState(
            source_id="WTG_01",
            node_key="TotW",
            value="1200.0",
            observed_at=datetime.now(tz=UTC),
        )
    ]


def test_acquire_builds_state_data_from_plan_and_adapter() -> None:
    """Coordinate the plan and acquisition port into source-state data."""
    plan = _build_plan()
    acquisition_port = FakeSourceAcquisitionPort(_build_states())
    role = SourceStateReadRole(acquisition_port=acquisition_port)

    data = asyncio.run(role.acquire(plan))

    assert data.runtime_config_id == 101
    assert data.acquisition_status == "SUCCEEDED"
    assert len(data.acquired_states) == 1
    assert data.acquired_states[0].source_id == "WTG_01"
    assert len(acquisition_port.requests) == 1
    assert acquisition_port.requests[0].items[0].locator.endswith("WTG_01.TotW")


def test_acquire_returns_failed_and_last_error_when_adapter_raises() -> None:
    """Capture acquisition exceptions as FAILED state instead of raising."""
    plan = _build_plan()
    role = SourceStateReadRole(
        acquisition_port=FakeSourceAcquisitionPort([], error=TimeoutError("timeout")),
    )

    data = asyncio.run(role.acquire(plan))

    assert data.acquisition_status == "FAILED"
    assert data.last_error == "timeout"
    assert data.acquired_states == []


def test_acquire_returns_empty_when_no_states_are_received() -> None:
    """Return EMPTY when the adapter returns an empty state list."""
    plan = _build_plan()
    role = SourceStateReadRole(
        acquisition_port=FakeSourceAcquisitionPort([]),
    )

    data = asyncio.run(role.acquire(plan))

    assert data.acquisition_status == "EMPTY"
    assert data.acquired_states == []
    assert data.last_error is None
