"""Unit tests for subscribe acquisition use case."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime

from whale.ingest.ports.state import ModeAwareSourceStateCachePort
from whale.ingest.ports.source.source_acquisition_port import SourceSubscriptionHandle
from whale.ingest.usecases.dtos.acquired_node_state import AcquiredNodeState
from whale.ingest.usecases.dtos.acquisition_execution_options import (
    AcquisitionExecutionOptions,
)
from whale.ingest.usecases.dtos.acquisition_item_data import AcquisitionItemData
from whale.ingest.usecases.dtos.source_acquisition_request import (
    SourceAcquisitionRequest,
)
from whale.ingest.usecases.dtos.source_connection_data import SourceConnectionData
from whale.ingest.usecases.subscribe_acquisition_usecase import (
    SubscribeAcquisitionUseCase,
)


class FakeSubscriptionHandle(SourceSubscriptionHandle):
    def __init__(self) -> None:
        self.close_calls = 0

    async def close(self) -> None:
        self.close_calls += 1


class FakeSourceAcquisitionPort:
    def __init__(self) -> None:
        self.read_calls: list[SourceConnectionData] = []
        self.start_calls: list[SourceConnectionData] = []
        self.handles: list[FakeSubscriptionHandle] = []

    async def read(
        self,
        execution: object,
        connection: SourceConnectionData,
        items: list[AcquisitionItemData],
    ) -> list[AcquiredNodeState]:
        del execution, items
        self.read_calls.append(connection)
        return [
            AcquiredNodeState(
                source_id=connection.ld_name,
                node_key="TotW",
                value="41.0",
                observed_at=datetime.now(tz=UTC),
            )
        ]

    async def start_subscription(
        self,
        execution: object,
        connection: SourceConnectionData,
        items: list[AcquisitionItemData],
        *,
        state_received: object,
    ) -> SourceSubscriptionHandle:
        del execution, items
        self.start_calls.append(connection)
        handle = FakeSubscriptionHandle()
        self.handles.append(handle)
        assert callable(state_received)
        await state_received(
            [
                AcquiredNodeState(
                    source_id=connection.ld_name,
                    node_key="TotW",
                    value="42.0",
                    observed_at=datetime.now(tz=UTC),
                )
            ]
        )
        return handle


class FakeSourceAcquisitionPortRegistry:
    def __init__(self, port: FakeSourceAcquisitionPort) -> None:
        self._port = port

    def get(self, protocol: str) -> FakeSourceAcquisitionPort:
        assert protocol == "opcua"
        return self._port


class FakeModeAwareSourceStateCachePort(ModeAwareSourceStateCachePort):
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, list[AcquiredNodeState]]] = []

    def store_many(self, model_id: str, acquired_states: list[AcquiredNodeState]) -> int:
        return self.store_many_for_mode("ONCE", model_id, acquired_states)

    def store_many_for_mode(
        self,
        acquisition_mode: str,
        model_id: str,
        acquired_states: list[AcquiredNodeState],
    ) -> int:
        self.calls.append((acquisition_mode, model_id, list(acquired_states)))
        return len(acquired_states)


def _build_request() -> SourceAcquisitionRequest:
    return SourceAcquisitionRequest(
        request_id="subscription-1",
        task_id=101,
        execution=AcquisitionExecutionOptions(
            protocol="opcua",
            transport="tcp",
            acquisition_mode="SUBSCRIBE",
            interval_ms=100,
            max_iteration=None,
            request_timeout_ms=500,
            freshness_timeout_ms=30000,
            alive_timeout_ms=60000,
        ),
        connections=[
            SourceConnectionData(
                host="127.0.0.1",
                port=4840,
                ied_name="IED_01",
                ld_name="LD_01",
                namespace_uri="urn:test",
            ),
            SourceConnectionData(
                host="127.0.0.2",
                port=4840,
                ied_name="IED_02",
                ld_name="LD_02",
                namespace_uri="urn:test",
            ),
        ],
        items=[AcquisitionItemData(key="TotW", profile_item_id=1, relative_path="TotW")],
    )


def test_start_creates_sessions_for_all_connections() -> None:
    port = FakeSourceAcquisitionPort()
    cache = FakeModeAwareSourceStateCachePort()
    use_case = SubscribeAcquisitionUseCase(
        acquisition_port_registry=FakeSourceAcquisitionPortRegistry(port),
        state_cache_port=cache,
    )

    sessions = asyncio.run(use_case.start(_build_request()))

    assert len(sessions) == 2
    assert [connection.ld_name for connection in port.read_calls] == ["LD_01", "LD_02"]
    assert [connection.ld_name for connection in port.start_calls] == ["LD_01", "LD_02"]
    assert sorted(model_id for _, model_id, _ in cache.calls) == [
        "LD_01",
        "LD_01",
        "LD_02",
        "LD_02",
    ]


def test_execute_waits_for_stop_and_closes_sessions() -> None:
    port = FakeSourceAcquisitionPort()
    cache = FakeModeAwareSourceStateCachePort()
    use_case = SubscribeAcquisitionUseCase(
        acquisition_port_registry=FakeSourceAcquisitionPortRegistry(port),
        state_cache_port=cache,
    )
    stop_event = asyncio.Event()

    async def _run() -> None:
        task = asyncio.create_task(use_case.execute(_build_request(), stop_event))
        await asyncio.sleep(0.05)
        stop_event.set()
        await task

    asyncio.run(_run())

    assert len(port.handles) == 2
    assert all(handle.close_calls == 1 for handle in port.handles)
