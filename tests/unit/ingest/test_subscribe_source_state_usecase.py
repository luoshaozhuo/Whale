"""Unit tests for the subscribe-source-state use case."""

from __future__ import annotations

import asyncio
import csv
from datetime import UTC, datetime
from pathlib import Path
from threading import Event

from whale.ingest.adapters.store.file_variable_state_repository import (
    FileVariableStateRepository,
)
from whale.ingest.ports.source.source_acquisition_port import SourceAcquisitionPort
from whale.ingest.usecases.dtos.acquired_node_state import AcquiredNodeState
from whale.ingest.usecases.dtos.acquisition_item_data import AcquisitionItemData
from whale.ingest.usecases.dtos.source_acquisition_definition import (
    SourceAcquisitionDefinition,
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
    """Capture subscription requests and require concurrent startup."""

    def __init__(self) -> None:
        """Initialize captured requests and the startup barrier."""
        self.requests: list[SourceSubscriptionRequest] = []
        self._release = asyncio.Event()

    async def read(self, request: object) -> list[AcquiredNodeState]:
        """Unused pull hook required by the acquisition-port contract."""
        del request
        raise NotImplementedError

    async def subscribe(self, request: SourceSubscriptionRequest) -> None:
        """Capture the request, wait for all subscriptions, then emit one state."""
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


class FakeSourceStateStorePort:
    """Capture stored source-state batches."""

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


def _read_csv_rows(path: Path) -> list[dict[str, str]]:
    """Read CSV records produced by the file-backed repository."""
    with path.open("r", encoding="utf-8", newline="") as input_file:
        return list(csv.DictReader(input_file))


def test_execute_starts_all_source_subscriptions_and_stores_updates() -> None:
    """Start one subscription per runtime config and persist incoming updates."""
    runtime_configs = (
        _build_runtime_config(101, "WTG_01"),
        _build_runtime_config(102, "WTG_02"),
    )
    acquisition_port = ConcurrentFakeSourceAcquisitionPort()
    store_port = FakeSourceStateStorePort()
    use_case = SubscribeSourceStateUseCase(
        acquisition_definition_port=FakeAcquisitionDefinitionPort(
            {
                101: _build_definition("model_1", "WTG_01"),
                102: _build_definition("model_2", "WTG_02"),
            }
        ),
        acquisition_port_registry=FakeSourceAcquisitionPortRegistry({"opcua": acquisition_port}),
        store_port=store_port,
    )

    asyncio.run(use_case.execute(runtime_configs=runtime_configs, stop_event=Event()))

    assert [request.source_id for request in acquisition_port.requests] == ["WTG_01", "WTG_02"]
    assert [model_id for model_id, _ in store_port.calls] == ["model_1", "model_2"]
    assert [states[0].source_id for _, states in store_port.calls] == ["WTG_01", "WTG_02"]


def test_execute_routes_subscription_results_to_subscription_capture_file(
    tmp_path: Path,
) -> None:
    """Write subscription updates into the dedicated subscription capture file."""
    runtime_configs = (
        _build_runtime_config(101, "WTG_01"),
        _build_runtime_config(102, "WTG_02"),
    )
    acquisition_port = ConcurrentFakeSourceAcquisitionPort()
    use_case = SubscribeSourceStateUseCase(
        acquisition_definition_port=FakeAcquisitionDefinitionPort(
            {
                101: _build_definition("model_1", "WTG_01"),
                102: _build_definition("model_2", "WTG_02"),
            }
        ),
        acquisition_port_registry=FakeSourceAcquisitionPortRegistry({"opcua": acquisition_port}),
        store_port=FileVariableStateRepository(tmp_path),
    )

    asyncio.run(use_case.execute(runtime_configs=runtime_configs, stop_event=Event()))

    records = _read_csv_rows(tmp_path / "subscription-results.csv")
    assert [record["device_code"] for record in records] == ["WTG_01", "WTG_02"]
    assert [record["model_id"] for record in records] == ["model_1", "model_2"]
    assert [record["variable_key"] for record in records] == ["TotW", "TotW"]
