"""Unit tests for the subscribe-source-state use case."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from threading import Event

from whale.ingest.ports.state import ModeAwareSourceStateCachePort
from whale.ingest.ports.source.source_acquisition_port import SourceAcquisitionPort
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
from whale.ingest.usecases.dtos.source_subscription_request import (
    SourceSubscriptionRequest,
)
from whale.ingest.usecases.subscribe_source_state_usecase import (
    SubscribeSourceStateUseCase,
)


class FakeAcquisitionDefinitionPort:
    """Return acquisition definitions keyed by runtime config id."""

    def __init__(self, definitions: dict[int, SourceAcquisitionDefinition]) -> None:
        """Store the definitions available to the use case."""
        self._definitions = dict(definitions)

    def get_config(
        self,
        runtime_config: SourceRuntimeConfigData,
    ) -> SourceAcquisitionDefinition:
        """Return acquisition config for the requested runtime config."""
        return self._definitions[runtime_config.runtime_config_id]


class ConcurrentFakeSourceAcquisitionPort:
    """Capture initial reads and subscription requests for startup ordering tests."""

    def __init__(self) -> None:
        """Initialize captured requests and the startup barrier."""
        self.requests: list[SourceSubscriptionRequest] = []
        self.read_requests: list[SourceAcquisitionRequest] = []
        self._release = asyncio.Event()

    async def read(self, request: SourceAcquisitionRequest) -> list[AcquiredNodeState]:
        """Capture the initial full read and return one starting value."""
        self.read_requests.append(request)
        return [
            AcquiredNodeState(
                source_id=request.source_id,
                node_key=request.items[0].key,
                value="41.0",
                observed_at=datetime.now(tz=UTC),
            )
        ]

    async def subscribe(self, request: SourceSubscriptionRequest) -> None:
        """Capture the request, wait for all subscriptions, then emit one state."""
        assert len(self.read_requests) == 2
        self.requests.append(request)
        if len(self.requests) >= 2:
            self._release.set()

        await asyncio.wait_for(self._release.wait(), timeout=0.2)
        assert request.state_received is not None
        await request.state_received(
            [
                AcquiredNodeState(
                    source_id=request.source_id,
                    node_key=request.items[0].key,
                    value="42.0",
                    observed_at=datetime.now(tz=UTC),
                )
            ]
        )


class FakeSourceAcquisitionPortRegistry:
    """Resolve fake acquisition ports by protocol."""

    def __init__(self, ports_by_protocol: dict[str, SourceAcquisitionPort]) -> None:
        """Store the fake acquisition ports."""
        self._ports_by_protocol = dict(ports_by_protocol)

    def get(self, protocol: str) -> SourceAcquisitionPort:
        """Return the configured acquisition port."""
        return self._ports_by_protocol[protocol]


class FakeSourceStateCachePort:
    """Capture latest-state refresh batches."""

    def __init__(self) -> None:
        """Initialize one empty call list."""
        self.calls: list[tuple[str, list[AcquiredNodeState]]] = []

    def store_many(
        self,
        model_id: str,
        acquired_states: list[AcquiredNodeState],
    ) -> int:
        """Capture stored states and return the processed row count."""
        self.calls.append((model_id, list(acquired_states)))
        return len(acquired_states)


class FakeSnapshotEmitter:
    """Capture snapshot emission calls for subscribe tests."""

    def __init__(self) -> None:
        """Initialize one empty call list."""
        self.call_count = 0

    def execute(self) -> object:
        """Record one snapshot emission call."""
        self.call_count += 1
        return {"emitted": True}


class FakeModeAwareSourceStateCachePort(ModeAwareSourceStateCachePort):
    """Capture mode-aware latest-state updates for subscription tests."""

    def __init__(self) -> None:
        """Initialize one empty mode-aware call list."""
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
        """Capture one mode-specific state refresh batch."""
        self.calls_by_mode.append((acquisition_mode, model_id, list(acquired_states)))
        return len(acquired_states)


def _build_runtime_config(runtime_config_id: int, source_id: str) -> SourceRuntimeConfigData:
    """Build one subscription runtime config for tests."""
    return SourceRuntimeConfigData(
        runtime_config_id=runtime_config_id,
        source_id=source_id,
        protocol="opcua",
        acquisition_mode="SUBSCRIPTION",
        interval_ms=0,
        enabled=True,
    )


def _build_definition(model_id: str, source_id: str) -> SourceAcquisitionDefinition:
    """Build one acquisition definition for subscription tests."""
    return SourceAcquisitionDefinition(
        model_id=model_id,
        connection=SourceConnectionData(endpoint=f"opc.tcp://127.0.0.1/{source_id}"),
        items=[
            AcquisitionItemData(
                key="TotW",
                locator=f"ns=2;s={source_id}.TotW",
            )
        ],
    )


def test_execute_starts_all_source_subscriptions_and_stores_updates() -> None:
    """Read once before subscribe, then persist both initial and incremental updates."""
    runtime_configs = (
        _build_runtime_config(101, "WTG_01"),
        _build_runtime_config(102, "WTG_02"),
    )
    acquisition_port = ConcurrentFakeSourceAcquisitionPort()
    state_cache_port = FakeSourceStateCachePort()
    use_case = SubscribeSourceStateUseCase(
        acquisition_definition_port=FakeAcquisitionDefinitionPort(
            {
                101: _build_definition("model_1", "WTG_01"),
                102: _build_definition("model_2", "WTG_02"),
            }
        ),
        acquisition_port_registry=FakeSourceAcquisitionPortRegistry({"opcua": acquisition_port}),
        state_cache_port=state_cache_port,
    )

    asyncio.run(use_case.execute(runtime_configs=runtime_configs, stop_event=Event()))

    assert [request.source_id for request in acquisition_port.read_requests] == [
        "WTG_01",
        "WTG_02",
    ]
    assert [request.source_id for request in acquisition_port.requests] == ["WTG_01", "WTG_02"]
    assert [model_id for model_id, _ in state_cache_port.calls] == [
        "model_1",
        "model_2",
        "model_1",
        "model_2",
    ]
    assert [states[0].value for _, states in state_cache_port.calls] == [
        "41.0",
        "41.0",
        "42.0",
        "42.0",
    ]


def test_execute_routes_subscription_results_with_subscription_mode() -> None:
    """Tag both initial and incremental subscription updates with SUBSCRIPTION mode."""
    runtime_configs = (
        _build_runtime_config(101, "WTG_01"),
        _build_runtime_config(102, "WTG_02"),
    )
    acquisition_port = ConcurrentFakeSourceAcquisitionPort()
    state_cache_port = FakeModeAwareSourceStateCachePort()
    use_case = SubscribeSourceStateUseCase(
        acquisition_definition_port=FakeAcquisitionDefinitionPort(
            {
                101: _build_definition("model_1", "WTG_01"),
                102: _build_definition("model_2", "WTG_02"),
            }
        ),
        acquisition_port_registry=FakeSourceAcquisitionPortRegistry({"opcua": acquisition_port}),
        state_cache_port=state_cache_port,
    )

    asyncio.run(use_case.execute(runtime_configs=runtime_configs, stop_event=Event()))

    assert [mode for mode, _, _ in state_cache_port.calls_by_mode] == [
        "SUBSCRIPTION",
        "SUBSCRIPTION",
        "SUBSCRIPTION",
        "SUBSCRIPTION",
    ]
    flattened_states = [states[0] for _, _, states in state_cache_port.calls_by_mode]
    assert [state.source_id for state in flattened_states] == [
        "WTG_01",
        "WTG_02",
        "WTG_01",
        "WTG_02",
    ]
    assert [model_id for _, model_id, _ in state_cache_port.calls_by_mode] == [
        "model_1",
        "model_2",
        "model_1",
        "model_2",
    ]
    assert [state.value for state in flattened_states] == ["41.0", "41.0", "42.0", "42.0"]


def test_execute_emits_snapshot_for_initial_and_incremental_updates() -> None:
    """Emit snapshots for both initial reads and subscription updates."""
    runtime_configs = (
        _build_runtime_config(101, "WTG_01"),
        _build_runtime_config(102, "WTG_02"),
    )
    acquisition_port = ConcurrentFakeSourceAcquisitionPort()
    emitter = FakeSnapshotEmitter()
    use_case = SubscribeSourceStateUseCase(
        acquisition_definition_port=FakeAcquisitionDefinitionPort(
            {
                101: _build_definition("model_1", "WTG_01"),
                102: _build_definition("model_2", "WTG_02"),
            }
        ),
        acquisition_port_registry=FakeSourceAcquisitionPortRegistry({"opcua": acquisition_port}),
        state_cache_port=FakeSourceStateCachePort(),
        snapshot_emitter=emitter,
    )

    asyncio.run(use_case.execute(runtime_configs=runtime_configs, stop_event=Event()))

    assert emitter.call_count == 4
