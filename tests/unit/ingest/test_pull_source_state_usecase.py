"""Unit tests for the pull-source-state use case."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime

import pytest

from whale.ingest.ports.state import ModeAwareSourceStateCachePort
from whale.ingest.ports.source.source_acquisition_port import SourceAcquisitionPort
from whale.ingest.usecases.dtos.acquired_node_state import AcquiredNodeState
from whale.ingest.usecases.dtos.acquisition_item_data import AcquisitionItemData
from whale.ingest.usecases.dtos.acquisition_status import AcquisitionStatus
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
from whale.ingest.usecases.pull_source_state_usecase import (
    PullSourceStateUseCase,
)


class FakeAcquisitionDefinitionPort:
    """Fake acquisition-definition port for use-case tests."""

    def __init__(self, definition: SourceAcquisitionDefinition | None) -> None:
        """Store the definition returned to the role."""
        self._definition = definition

    def get_config(
        self,
        runtime_config: SourceRuntimeConfigData,
    ) -> SourceAcquisitionDefinition:
        """Return acquisition config for the requested runtime config."""
        if self._definition is None:
            raise LookupError(f"Definition for `{runtime_config.runtime_config_id}` was not found.")
        return self._definition


class FakeSourceAcquisitionPort:
    """Fake source-acquisition port for use-case tests."""

    def __init__(self, states: list[AcquiredNodeState], error: Exception | None = None) -> None:
        """Store the configured acquisition behavior."""
        self._states = list(states)
        self._error = error
        self.requests: list[SourceAcquisitionRequest] = []

    async def read(self, request: SourceAcquisitionRequest) -> list[AcquiredNodeState]:
        """Capture the request and return the configured states."""
        self.requests.append(request)
        if self._error is not None:
            raise self._error
        return list(self._states)

    async def subscribe(self, request: object) -> None:
        """Unused subscription hook required by the port contract."""
        del request
        raise NotImplementedError


class FakeSourceAcquisitionPortRegistry:
    """Resolve fake acquisition ports by protocol for use-case tests."""

    def __init__(self, ports_by_protocol: dict[str, SourceAcquisitionPort]) -> None:
        """Store fake acquisition ports keyed by protocol."""
        self._ports_by_protocol = dict(ports_by_protocol)

    def get(self, protocol: str) -> SourceAcquisitionPort:
        """Return the fake acquisition port or raise when unsupported."""
        try:
            return self._ports_by_protocol[protocol]
        except KeyError as exc:
            raise ValueError(f"Unsupported acquisition protocol: {protocol}") from exc


class FakeSourceStateCachePort:
    """Fake source-state cache for use-case tests."""

    def __init__(self, updated_count: int = 0) -> None:
        """Store the count returned from `store_many`."""
        self._updated_count = updated_count
        self.calls: list[tuple[str, list[AcquiredNodeState]]] = []

    def store_many(
        self,
        model_id: str,
        acquired_states: list[AcquiredNodeState],
    ) -> int:
        """Capture the call and return the configured update count."""
        self.calls.append((model_id, list(acquired_states)))
        return self._updated_count


class FakeSnapshotEmitter:
    """Capture snapshot emission calls for use-case tests."""

    def __init__(self) -> None:
        """Initialize the call counter."""
        self.call_count = 0

    def execute(self) -> object:
        """Record one snapshot emission call."""
        self.call_count += 1
        return {"emitted": True}


class FakeModeAwareSourceStateCachePort(ModeAwareSourceStateCachePort):
    """Capture mode-aware cache updates for use-case tests."""

    def __init__(self, updated_count: int = 0) -> None:
        """Store the count returned from state-cache refresh calls."""
        self._updated_count = updated_count
        self.calls_by_mode: list[tuple[str, str, list[AcquiredNodeState]]] = []

    def store_many(self, model_id: str, acquired_states: list[AcquiredNodeState]) -> int:
        """Capture default updates as ONCE mode refreshes."""
        return self.store_many_for_mode("ONCE", model_id, acquired_states)

    def store_many_for_mode(
        self,
        acquisition_mode: str,
        model_id: str,
        acquired_states: list[AcquiredNodeState],
    ) -> int:
        """Capture mode-specific cache refresh calls."""
        self.calls_by_mode.append((acquisition_mode, model_id, list(acquired_states)))
        return self._updated_count


class MultiDefinitionPort:
    """Return acquisition definitions keyed by runtime config id."""

    def __init__(self, definitions: dict[int, SourceAcquisitionDefinition]) -> None:
        """Store definitions for later lookup."""
        self._definitions = dict(definitions)

    def get_config(
        self,
        runtime_config: SourceRuntimeConfigData,
    ) -> SourceAcquisitionDefinition:
        """Return acquisition config for the requested runtime config."""
        try:
            return self._definitions[runtime_config.runtime_config_id]
        except KeyError as exc:
            raise LookupError(runtime_config.runtime_config_id) from exc


class SlowConcurrentAcquisitionPort:
    """Simulate slow reads and record the highest observed concurrency."""

    def __init__(self, states: list[AcquiredNodeState], delay_seconds: float = 0.05) -> None:
        """Store deterministic states and the per-read delay."""
        self._states = list(states)
        self._delay_seconds = delay_seconds
        self._active_reads = 0
        self.max_concurrent_reads = 0

    async def read(self, request: SourceAcquisitionRequest) -> list[AcquiredNodeState]:
        """Sleep briefly to make overlapping reads observable."""
        del request
        self._active_reads += 1
        self.max_concurrent_reads = max(self.max_concurrent_reads, self._active_reads)

        try:
            await asyncio.sleep(self._delay_seconds)
            return list(self._states)
        finally:
            self._active_reads -= 1

    async def subscribe(self, request: object) -> None:
        """Unused subscription hook required by the port contract."""
        del request
        raise NotImplementedError


def _build_runtime_config(enabled: bool = True) -> SourceRuntimeConfigData:
    """Build one runtime config for use-case tests."""
    return SourceRuntimeConfigData(
        runtime_config_id=101,
        source_id="WTG_01",
        protocol="opcua",
        acquisition_mode="ONCE",
        interval_ms=0,
        enabled=enabled,
    )


def _build_runtime_config_for_mode(
    acquisition_mode: str, interval_ms: int
) -> SourceRuntimeConfigData:
    """Build one runtime config with a custom acquisition mode."""
    runtime_config = _build_runtime_config()
    return SourceRuntimeConfigData(
        runtime_config_id=runtime_config.runtime_config_id,
        source_id=runtime_config.source_id,
        protocol=runtime_config.protocol,
        acquisition_mode=acquisition_mode,
        interval_ms=interval_ms,
        enabled=runtime_config.enabled,
    )


def _build_runtime_config_with_id(runtime_config_id: int) -> SourceRuntimeConfigData:
    """Build one runtime config with a custom identifier."""
    runtime_config = _build_runtime_config()
    return SourceRuntimeConfigData(
        runtime_config_id=runtime_config_id,
        source_id=runtime_config.source_id,
        protocol=runtime_config.protocol,
        acquisition_mode=runtime_config.acquisition_mode,
        interval_ms=runtime_config.interval_ms,
        enabled=runtime_config.enabled,
    )


def _build_definition() -> SourceAcquisitionDefinition:
    """Build one acquisition definition for use-case tests."""
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


def _build_definition_with_runtime_config_id(runtime_config_id: int) -> SourceAcquisitionDefinition:
    """Build one acquisition definition with a custom runtime-config identifier."""
    del runtime_config_id
    return _build_definition()


def _build_states() -> list[AcquiredNodeState]:
    """Build one acquired-state list for use-case tests."""
    return [
        AcquiredNodeState(
            source_id="WTG_01",
            node_key="TotW",
            value="1200.0",
            observed_at=datetime.now(tz=UTC),
        )
    ]


def _assert_result_execution_window(
    result_started_at: datetime,
    result_ended_at: datetime,
    window_started_at: datetime,
    window_ended_at: datetime,
) -> None:
    """Assert that result timestamps stay within one test execution window."""
    assert window_started_at <= result_started_at <= result_ended_at <= window_ended_at
    assert result_started_at.tzinfo is not None
    assert result_ended_at.tzinfo is not None


def test_execute_returns_failed_when_definition_is_missing() -> None:
    """Return FAILED when the acquisition definition cannot be built."""
    runtime_config = _build_runtime_config()
    state_cache_port = FakeSourceStateCachePort(updated_count=1)
    use_case = PullSourceStateUseCase(
        acquisition_definition_port=FakeAcquisitionDefinitionPort(None),
        acquisition_port_registry=FakeSourceAcquisitionPortRegistry(
            {"opcua": FakeSourceAcquisitionPort(_build_states())}
        ),
        state_cache_port=state_cache_port,
    )

    result = asyncio.run(use_case.execute([runtime_config]))[0]

    assert result.runtime_config_id == 101
    assert result.status == "FAILED"
    assert "Definition for `101` was not found." == result.error_message


@pytest.mark.parametrize(
    ("acquisition_mode", "interval_ms"),
    [
        ("ONCE", 0),
        ("POLLING", 100),
    ],
)
def test_execute_routes_pull_results_to_mode_specific_cache_call(
    acquisition_mode: str,
    interval_ms: int,
) -> None:
    """Tag pull updates with the runtime acquisition mode when cache supports it."""
    runtime_config = _build_runtime_config_for_mode(acquisition_mode, interval_ms)
    state_cache_port = FakeModeAwareSourceStateCachePort(updated_count=1)
    use_case = PullSourceStateUseCase(
        acquisition_definition_port=FakeAcquisitionDefinitionPort(_build_definition()),
        acquisition_port_registry=FakeSourceAcquisitionPortRegistry(
            {"opcua": FakeSourceAcquisitionPort(_build_states())}
        ),
        state_cache_port=state_cache_port,
    )

    window_started_at = datetime.now(tz=UTC)
    result = asyncio.run(use_case.execute([runtime_config]))[0]
    window_ended_at = datetime.now(tz=UTC)

    assert result.status is AcquisitionStatus.SUCCEEDED
    assert len(state_cache_port.calls_by_mode) == 1
    call_mode, model_id, states = state_cache_port.calls_by_mode[0]
    assert call_mode == acquisition_mode
    assert model_id == "goldwind_gw121_opcua"
    assert [state.node_key for state in states] == ["TotW"]
    assert [state.source_id for state in states] == ["WTG_01"]
    _assert_result_execution_window(
        result.started_at, result.ended_at, window_started_at, window_ended_at
    )


def test_execute_returns_succeeded_and_persists_states() -> None:
    """Persist acquired states and expose a successful outcome."""
    runtime_config = _build_runtime_config()
    states = _build_states()
    acquisition_port = FakeSourceAcquisitionPort(states)
    state_cache_port = FakeSourceStateCachePort(updated_count=1)
    use_case = PullSourceStateUseCase(
        acquisition_definition_port=FakeAcquisitionDefinitionPort(_build_definition()),
        acquisition_port_registry=FakeSourceAcquisitionPortRegistry({"opcua": acquisition_port}),
        state_cache_port=state_cache_port,
    )

    window_started_at = datetime.now(tz=UTC)
    result = asyncio.run(use_case.execute([runtime_config]))[0]
    window_ended_at = datetime.now(tz=UTC)

    assert result.runtime_config_id == 101
    assert result.status == "SUCCEEDED"
    assert result.error_message is None
    _assert_result_execution_window(
        result.started_at, result.ended_at, window_started_at, window_ended_at
    )


def test_execute_emits_snapshot_once_when_any_runtime_config_succeeds() -> None:
    """Emit one full snapshot once after successful cache refreshes."""
    runtime_config = _build_runtime_config()
    states = _build_states()
    emitter = FakeSnapshotEmitter()
    use_case = PullSourceStateUseCase(
        acquisition_definition_port=FakeAcquisitionDefinitionPort(_build_definition()),
        acquisition_port_registry=FakeSourceAcquisitionPortRegistry(
            {"opcua": FakeSourceAcquisitionPort(states)}
        ),
        state_cache_port=FakeSourceStateCachePort(updated_count=1),
        snapshot_emitter=emitter,
    )

    result = asyncio.run(use_case.execute([runtime_config]))[0]

    assert result.status is AcquisitionStatus.SUCCEEDED
    assert emitter.call_count == 1


def test_execute_returns_empty_when_acquisition_has_no_results() -> None:
    """Return EMPTY without persisting any state rows."""
    runtime_config = _build_runtime_config()
    state_cache_port = FakeSourceStateCachePort(updated_count=99)
    use_case = PullSourceStateUseCase(
        acquisition_definition_port=FakeAcquisitionDefinitionPort(_build_definition()),
        acquisition_port_registry=FakeSourceAcquisitionPortRegistry(
            {"opcua": FakeSourceAcquisitionPort([])}
        ),
        state_cache_port=state_cache_port,
    )

    window_started_at = datetime.now(tz=UTC)
    result = asyncio.run(use_case.execute([runtime_config]))[0]
    window_ended_at = datetime.now(tz=UTC)

    assert result.runtime_config_id == 101
    assert result.status == "EMPTY"
    _assert_result_execution_window(
        result.started_at, result.ended_at, window_started_at, window_ended_at
    )
    assert state_cache_port.calls == []
    assert result.status is AcquisitionStatus.EMPTY


def test_execute_returns_failed_when_acquisition_raises() -> None:
    """Return FAILED instead of bubbling one acquisition exception."""
    runtime_config = _build_runtime_config()
    state_cache_port = FakeSourceStateCachePort(updated_count=1)
    use_case = PullSourceStateUseCase(
        acquisition_definition_port=FakeAcquisitionDefinitionPort(_build_definition()),
        acquisition_port_registry=FakeSourceAcquisitionPortRegistry(
            {"opcua": FakeSourceAcquisitionPort([], error=ConnectionError("boom"))}
        ),
        state_cache_port=state_cache_port,
    )

    window_started_at = datetime.now(tz=UTC)
    result = asyncio.run(use_case.execute([runtime_config]))[0]
    window_ended_at = datetime.now(tz=UTC)

    assert result.runtime_config_id == 101
    assert result.status == "FAILED"
    assert result.error_message == "boom"
    _assert_result_execution_window(
        result.started_at, result.ended_at, window_started_at, window_ended_at
    )
    assert state_cache_port.calls == []
    assert result.status is AcquisitionStatus.FAILED


def test_execute_many_pulls_runtime_configs_concurrently() -> None:
    """Run slow polling reads concurrently for multiple runtime configs."""
    first = _build_runtime_config_with_id(101)
    second = _build_runtime_config_with_id(102)
    acquisition_port = SlowConcurrentAcquisitionPort(_build_states())
    use_case = PullSourceStateUseCase(
        acquisition_definition_port=MultiDefinitionPort(
            {
                101: _build_definition_with_runtime_config_id(101),
                102: _build_definition_with_runtime_config_id(102),
            }
        ),
        acquisition_port_registry=FakeSourceAcquisitionPortRegistry({"opcua": acquisition_port}),
        state_cache_port=FakeSourceStateCachePort(updated_count=2),
        max_in_flight=2,
    )

    results = asyncio.run(use_case.execute([first, second]))

    assert [result.runtime_config_id for result in results] == [101, 102]
    assert all(result.status is AcquisitionStatus.SUCCEEDED for result in results)
    assert acquisition_port.max_concurrent_reads >= 2
