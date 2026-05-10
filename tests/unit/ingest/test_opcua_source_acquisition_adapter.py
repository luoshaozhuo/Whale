"""Unit tests for the OPC UA source-acquisition adapter."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

import pytest

from whale.ingest.adapters.source import opcua_source_acquisition_adapter as adapter_module
from whale.ingest.adapters.source.opcua_source_acquisition_adapter import (
    OpcUaSourceAcquisitionAdapter,
    OpcUaAdapterSubscriptionHandle,
)
from whale.ingest.usecases.dtos.acquired_node_state import AcquiredNodeState
from whale.ingest.usecases.dtos.acquisition_execution_options import (
    AcquisitionExecutionOptions,
)
from whale.ingest.usecases.dtos.acquisition_item_data import AcquisitionItemData
from whale.ingest.usecases.dtos.source_connection_data import SourceConnectionData


class FakeReaderHandle:
    def __init__(self) -> None:
        self.close_calls = 0

    async def close(self) -> None:
        self.close_calls += 1


class FakeReader:
    def __init__(self, *, fail_on_start: bool = False) -> None:
        self.fail_on_start = fail_on_start
        self.profile: object | None = None
        self.entered = 0
        self.exited = 0
        self.start_calls: list[tuple[list[str], int]] = []
        self.handle = FakeReaderHandle()

    async def __aenter__(self) -> "FakeReader":
        self.entered += 1
        return self

    async def __aexit__(self, exc_type: object, exc: object, tb: object) -> None:
        del exc_type, exc, tb
        self.exited += 1

    async def read(self, node_paths: list[str], *, fast_mode: bool = True) -> tuple[object, ...]:
        assert fast_mode is True
        return tuple(
            SimpleNamespace(path=node_path, value=1000.0 + index, source_timestamp=None)
            for index, node_path in enumerate(node_paths, start=1)
        )

    async def start_subscription(
        self,
        node_paths: list[str],
        *,
        interval_ms: int,
        on_data_change: Any,
    ) -> FakeReaderHandle:
        self.start_calls.append((list(node_paths), interval_ms))
        if self.fail_on_start:
            raise RuntimeError("subscribe failed")

        timestamp = datetime(2026, 4, 24, 9, 0, tzinfo=UTC)
        for index, node_path in enumerate(node_paths, start=1):
            node = SimpleNamespace(nodeid=SimpleNamespace(to_string=lambda path=node_path: path))
            data = SimpleNamespace(
                monitored_item=SimpleNamespace(
                    Value=SimpleNamespace(SourceTimestamp=timestamp)
                )
            )
            await on_data_change(node, 1000.0 + index, data)

        return self.handle


def _execution() -> AcquisitionExecutionOptions:
    return AcquisitionExecutionOptions(
        protocol="opcua",
        transport="tcp",
        acquisition_mode="SUBSCRIBE",
        interval_ms=100,
        max_iteration=None,
        request_timeout_ms=500,
        freshness_timeout_ms=30000,
        alive_timeout_ms=60000,
    )


def _connection() -> SourceConnectionData:
    return SourceConnectionData(
        host="127.0.0.1",
        port=4840,
        ied_name="IED_01",
        ld_name="LD_01",
        namespace_uri="urn:test",
    )


def _items() -> list[AcquisitionItemData]:
    return [
        AcquisitionItemData(key="TotW", profile_item_id=1, relative_path="MMXU1.TotW.mag.f"),
        AcquisitionItemData(key="Spd", profile_item_id=2, relative_path="MMXU1.Spd.mag.f"),
    ]


def test_read_resolves_relative_paths_with_namespace_uri(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_reader = FakeReader()
    monkeypatch.setattr(
        adapter_module,
        "OpcUaSourceReader",
        lambda profile: _attach_profile(fake_reader, profile),
    )
    adapter = OpcUaSourceAcquisitionAdapter()

    states = asyncio.run(adapter.read(_execution(), _connection(), _items()))

    assert getattr(fake_reader.profile, "endpoint") == "opcua.tcp://127.0.0.1:4840"
    assert [state.node_key for state in states] == ["TotW", "Spd"]
    assert [state.value for state in states] == ["1001.0", "1002.0"]


def test_start_subscription_returns_handle_without_closing_reader(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_reader = FakeReader()
    monkeypatch.setattr(
        adapter_module,
        "OpcUaSourceReader",
        lambda profile: _attach_profile(fake_reader, profile),
    )
    adapter = OpcUaSourceAcquisitionAdapter()
    received_states: list[AcquiredNodeState] = []

    async def state_received(states: list[AcquiredNodeState]) -> None:
        received_states.extend(states)

    handle = asyncio.run(
        adapter.start_subscription(
            _execution(),
            _connection(),
            _items(),
            state_received=state_received,
        )
    )

    assert isinstance(handle, OpcUaAdapterSubscriptionHandle)
    assert fake_reader.entered == 1
    assert fake_reader.exited == 0
    assert [state.node_key for state in received_states] == ["TotW", "Spd"]

    asyncio.run(handle.close())

    assert fake_reader.handle.close_calls == 1
    assert fake_reader.exited == 1


def test_start_subscription_failure_closes_reader(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_reader = FakeReader(fail_on_start=True)
    monkeypatch.setattr(
        adapter_module,
        "OpcUaSourceReader",
        lambda profile: _attach_profile(fake_reader, profile),
    )
    adapter = OpcUaSourceAcquisitionAdapter()

    async def state_received(states: list[AcquiredNodeState]) -> None:
        del states

    with pytest.raises(RuntimeError, match="subscribe failed"):
        asyncio.run(
            adapter.start_subscription(
                _execution(),
                _connection(),
                _items(),
                state_received=state_received,
            )
        )

    assert fake_reader.entered == 1
    assert fake_reader.exited == 1


def _attach_profile(fake_reader: FakeReader, profile: object) -> FakeReader:
    fake_reader.profile = profile
    return fake_reader
