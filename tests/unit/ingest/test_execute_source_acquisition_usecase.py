"""Unit tests for polling acquisition use case."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime

from whale.ingest.ports.state import ModeAwareSourceStateCachePort
from whale.ingest.usecases.dtos.acquired_node_state import AcquiredNodeState
from whale.ingest.usecases.dtos.acquisition_execution_options import (
    AcquisitionExecutionOptions,
)
from whale.ingest.usecases.dtos.acquisition_item_data import AcquisitionItemData
from whale.ingest.usecases.dtos.acquisition_status import AcquisitionStatus
from whale.ingest.usecases.dtos.source_acquisition_request import (
    SourceAcquisitionRequest,
)
from whale.ingest.usecases.dtos.source_connection_data import SourceConnectionData
from whale.ingest.usecases.polling_acquisition_usecase import (
    PollingAcquisitionUseCase,
)


class FakeSourceAcquisitionPort:
    def __init__(self, states: list[AcquiredNodeState]) -> None:
        self._states = list(states)
        self.read_calls: list[tuple[object, SourceConnectionData, list[AcquisitionItemData]]] = []

    async def read(
        self,
        execution: object,
        connection: SourceConnectionData,
        items: list[AcquisitionItemData],
    ) -> list[AcquiredNodeState]:
        self.read_calls.append((execution, connection, list(items)))
        return list(self._states)

    async def start_subscription(self, *args: object, **kwargs: object) -> object:
        del args, kwargs
        raise NotImplementedError


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
        request_id="request-1",
        task_id=101,
        execution=AcquisitionExecutionOptions(
            protocol="opcua",
            transport="tcp",
            acquisition_mode="POLLING",
            interval_ms=1000,
            max_iteration=5,
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


def _build_states() -> list[AcquiredNodeState]:
    return [
        AcquiredNodeState(
            source_id="LD_01",
            node_key="TotW",
            value="1200.0",
            observed_at=datetime.now(tz=UTC),
        )
    ]


def test_execute_once_expands_connections_and_forces_single_iteration() -> None:
    port = FakeSourceAcquisitionPort(_build_states())
    cache = FakeModeAwareSourceStateCachePort()
    use_case = PollingAcquisitionUseCase(
        acquisition_port_registry=FakeSourceAcquisitionPortRegistry(port),
        state_cache_port=cache,
    )

    results = asyncio.run(use_case.execute_once(_build_request()))

    assert len(results) == 2
    assert all(result.status is AcquisitionStatus.SUCCEEDED for result in results)
    assert [call[1].ld_name for call in port.read_calls] == ["LD_01", "LD_02"]
    assert all(call[0].max_iteration == 1 for call in port.read_calls)
    assert [model_id for _, model_id, _ in cache.calls] == ["LD_01", "LD_02"]
