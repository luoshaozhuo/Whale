"""Unit tests for the execute-source-acquisition use case."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime

import pytest

from whale.ingest.ports.state import ModeAwareSourceStateCachePort
from whale.ingest.ports.source.source_acquisition_port import SourceAcquisitionPort
from whale.ingest.usecases.dtos.acquired_node_state import AcquiredNodeState
from whale.ingest.usecases.dtos.acquisition_item_data import AcquisitionItemData
from whale.ingest.usecases.dtos.acquisition_status import AcquisitionStatus
from whale.ingest.usecases.dtos.source_acquisition_execution_plan import (
    SourceAcquisitionExecutionPlan,
)
from whale.ingest.usecases.dtos.source_acquisition_request import (
    SourceAcquisitionRequest,
)
from whale.ingest.usecases.dtos.source_connection_data import SourceConnectionData
from whale.ingest.usecases.execute_source_acquisition_usecase import (
    ExecuteSourceAcquisitionUseCase,
)


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


class FakeSourceAcquisitionPortRegistry:
    def __init__(self, ports_by_protocol: dict[str, SourceAcquisitionPort]) -> None:
        self._ports_by_protocol = dict(ports_by_protocol)

    def get(self, protocol: str) -> SourceAcquisitionPort:
        try:
            return self._ports_by_protocol[protocol]
        except KeyError as exc:
            raise ValueError(f"Unsupported acquisition protocol: {protocol}") from exc


class FakeSourceStateCachePort:
    def __init__(self, updated_count: int = 0) -> None:
        self._updated_count = updated_count
        self.calls: list[tuple[str, list[AcquiredNodeState]]] = []

    def store_many(self, model_id: str, acquired_states: list[AcquiredNodeState]) -> int:
        self.calls.append((model_id, list(acquired_states)))
        return self._updated_count


class FakeModeAwareSourceStateCachePort(ModeAwareSourceStateCachePort):
    def __init__(self, updated_count: int = 0) -> None:
        self._updated_count = updated_count
        self.calls_by_mode: list[tuple[str, str, list[AcquiredNodeState]]] = []

    def store_many(self, model_id: str, acquired_states: list[AcquiredNodeState]) -> int:
        return self.store_many_for_mode("ONCE", model_id, acquired_states)

    def store_many_for_mode(
        self,
        acquisition_mode: str,
        model_id: str,
        acquired_states: list[AcquiredNodeState],
    ) -> int:
        self.calls_by_mode.append((acquisition_mode, model_id, list(acquired_states)))
        return self._updated_count


class SlowConcurrentAcquisitionPort:
    def __init__(self, states: list[AcquiredNodeState], delay_seconds: float = 0.05) -> None:
        self._states = list(states)
        self._delay_seconds = delay_seconds
        self._active_reads = 0
        self.max_concurrent_reads = 0

    async def read(self, request: SourceAcquisitionRequest) -> list[AcquiredNodeState]:
        del request
        self._active_reads += 1
        self.max_concurrent_reads = max(self.max_concurrent_reads, self._active_reads)
        try:
            await asyncio.sleep(self._delay_seconds)
            return list(self._states)
        finally:
            self._active_reads -= 1

    async def subscribe(self, request: object) -> None:
        del request
        raise NotImplementedError


def _build_plan(
    plan_id: str = "plan-1",
    task_id: int = 101,
    protocol: str = "opcua",
    acquisition_mode: str = "ONCE",
) -> SourceAcquisitionExecutionPlan:
    return SourceAcquisitionExecutionPlan(
        plan_id=plan_id,
        task_id=task_id,
        ld_instance_id=0,
        model_id="goldwind_gw121_opcua",
        acquisition_mode=acquisition_mode,
        protocol=protocol,
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


def test_execute_returns_succeeded_and_persists_states() -> None:
    """Persist acquired states and expose a successful outcome."""
    plan = _build_plan()
    states = _build_states()
    acquisition_port = FakeSourceAcquisitionPort(states)
    state_cache_port = FakeSourceStateCachePort(updated_count=1)
    use_case = ExecuteSourceAcquisitionUseCase(
        acquisition_port_registry=FakeSourceAcquisitionPortRegistry({"opcua": acquisition_port}),
        state_cache_port=state_cache_port,
    )

    window_started_at = datetime.now(tz=UTC)
    result = asyncio.run(use_case.execute([plan]))[0]
    window_ended_at = datetime.now(tz=UTC)

    assert result.task_id == 101
    assert result.status == "SUCCEEDED"
    assert result.error_message is None
    assert window_started_at <= result.started_at <= result.ended_at <= window_ended_at
    assert result.started_at.tzinfo is not None
    assert result.ended_at.tzinfo is not None


@pytest.mark.parametrize(
    ("acquisition_mode",),
    [("ONCE",), ("POLLING",)],
)
def test_execute_routes_results_to_mode_specific_cache_call(acquisition_mode: str) -> None:
    """Tag acquisition updates with the runtime acquisition mode when cache supports it."""
    plan = _build_plan(acquisition_mode=acquisition_mode)
    state_cache_port = FakeModeAwareSourceStateCachePort(updated_count=1)
    use_case = ExecuteSourceAcquisitionUseCase(
        acquisition_port_registry=FakeSourceAcquisitionPortRegistry(
            {"opcua": FakeSourceAcquisitionPort(_build_states())}
        ),
        state_cache_port=state_cache_port,
    )

    result = asyncio.run(use_case.execute([plan]))[0]

    assert result.status is AcquisitionStatus.SUCCEEDED
    assert len(state_cache_port.calls_by_mode) == 1
    call_mode, _, _ = state_cache_port.calls_by_mode[0]
    assert call_mode == acquisition_mode


def test_execute_returns_empty_when_acquisition_has_no_results() -> None:
    """Return EMPTY without persisting any state rows."""
    plan = _build_plan()
    state_cache_port = FakeSourceStateCachePort(updated_count=99)
    use_case = ExecuteSourceAcquisitionUseCase(
        acquisition_port_registry=FakeSourceAcquisitionPortRegistry(
            {"opcua": FakeSourceAcquisitionPort([])}
        ),
        state_cache_port=state_cache_port,
    )

    result = asyncio.run(use_case.execute([plan]))[0]

    assert result.task_id == 101
    assert result.status == "EMPTY"
    assert state_cache_port.calls == []
    assert result.status is AcquisitionStatus.EMPTY


def test_execute_returns_failed_when_acquisition_raises() -> None:
    """Return FAILED instead of bubbling one acquisition exception."""
    plan = _build_plan()
    state_cache_port = FakeSourceStateCachePort(updated_count=1)
    use_case = ExecuteSourceAcquisitionUseCase(
        acquisition_port_registry=FakeSourceAcquisitionPortRegistry(
            {"opcua": FakeSourceAcquisitionPort([], error=ConnectionError("boom"))}
        ),
        state_cache_port=state_cache_port,
    )

    result = asyncio.run(use_case.execute([plan]))[0]

    assert result.task_id == 101
    assert result.status == "FAILED"
    assert result.error_message == "boom"
    assert state_cache_port.calls == []
    assert result.status is AcquisitionStatus.FAILED


def test_execute_many_plans_concurrently() -> None:
    """Run slow reads concurrently for multiple plans."""
    first = _build_plan(plan_id="plan-1", task_id=101)
    second = _build_plan(plan_id="plan-2", task_id=102)
    acquisition_port = SlowConcurrentAcquisitionPort(_build_states())
    use_case = ExecuteSourceAcquisitionUseCase(
        acquisition_port_registry=FakeSourceAcquisitionPortRegistry({"opcua": acquisition_port}),
        state_cache_port=FakeSourceStateCachePort(updated_count=2),
        max_in_flight=2,
    )

    results = asyncio.run(use_case.execute([first, second]))

    assert [result.task_id for result in results] == [101, 102]
    assert all(result.status is AcquisitionStatus.SUCCEEDED for result in results)
    assert acquisition_port.max_concurrent_reads >= 2
