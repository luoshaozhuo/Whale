"""Unit tests for the OPC UA source-acquisition adapter."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime

import pytest

from whale.ingest.adapters.source import opcua_source_acquisition_adapter as adapter_module
from whale.ingest.adapters.source.opcua_source_acquisition_adapter import (
    OpcUaAdapterSubscriptionHandle,
    OpcUaSourceAcquisitionAdapter,
)
from whale.ingest.usecases.dtos.acquired_node_state import AcquiredNodeStateBatch
from whale.ingest.usecases.dtos.source_acquisition_request import (
    AcquisitionExecutionOptions,
    AcquisitionItemData,
)
from whale.ingest.usecases.dtos.source_connection_data import SourceConnectionData
from whale.shared.source.models import (
    SourceDataChange,
    SourceDataChangeBatch,
    SourceReadPoint,
)


class FakeReaderHandle:
    def __init__(self) -> None:
        self.close_calls = 0

    async def close(self) -> None:
        self.close_calls += 1


class FakeReader:
    def __init__(
        self,
        *,
        fail_on_start: bool = False,
        read_points: tuple[SourceReadPoint, ...] | None = None,
        subscription_batch: SourceDataChangeBatch | None = None,
    ) -> None:
        self.fail_on_start = fail_on_start
        self.profile: object | None = None
        self.entered = 0
        self.exited = 0
        self.read_calls: list[tuple[list[str], bool]] = []
        self.start_calls: list[tuple[list[str], int]] = []
        self.handle = FakeReaderHandle()
        self._read_points = read_points or ()
        self._subscription_batch = subscription_batch

    async def __aenter__(self) -> "FakeReader":
        self.entered += 1
        return self

    async def __aexit__(self, exc_type: object, exc: object, tb: object) -> None:
        del exc_type, exc, tb
        self.exited += 1

    async def read(
        self,
        addresses: list[str],
        *,
        include_metadata: bool = False,
    ) -> tuple[SourceReadPoint, ...]:
        self.read_calls.append((list(addresses), include_metadata))
        return self._read_points

    async def start_subscription(
        self,
        addresses: list[str],
        *,
        interval_ms: int,
        on_data_change: Callable[[SourceDataChangeBatch], Awaitable[None]],
    ) -> FakeReaderHandle:
        self.start_calls.append((list(addresses), interval_ms))
        if self.fail_on_start:
            raise RuntimeError("subscribe failed")

        if self._subscription_batch is not None:
            await on_data_change(self._subscription_batch)

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
        AcquisitionItemData(
            key="TotW",
            profile_item_id=1,
            relative_path="MMXU1.TotW.mag.f",
        ),
        AcquisitionItemData(
            key="Spd",
            profile_item_id=2,
            relative_path="MMXU1.Spd.mag.f",
        ),
    ]


def test_read_returns_one_ingest_batch_from_reader_points(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed_at = datetime(2026, 4, 24, 9, 0, tzinfo=UTC)
    fake_reader = FakeReader(
        read_points=(
            SourceReadPoint(
                path="nsu=urn:test;s=MMXU1.TotW.mag.f",
                value=1001.0,
                status="Good",
                source_timestamp=observed_at,
                server_timestamp=observed_at,
            ),
            SourceReadPoint(
                path="nsu=urn:test;s=MMXU1.Spd.mag.f",
                value=1002.0,
                status="Good",
                source_timestamp=observed_at,
                server_timestamp=observed_at,
            ),
        )
    )
    monkeypatch.setattr(
        adapter_module,
        "OpcUaSourceReader",
        lambda profile: _attach_profile(fake_reader, profile),
    )

    batch = asyncio.run(
        OpcUaSourceAcquisitionAdapter().read(_execution(), _connection(), _items())
    )

    assert isinstance(batch, AcquiredNodeStateBatch)
    assert getattr(fake_reader.profile, "endpoint") == "opcua.tcp://127.0.0.1:4840"
    assert fake_reader.read_calls == [
        (
            [
                "nsu=urn:test;s=MMXU1.TotW.mag.f",
                "nsu=urn:test;s=MMXU1.Spd.mag.f",
            ],
            True,
        )
    ]
    assert batch.source_id == "LD_01"
    assert batch.attributes == {"acquisition_kind": "read"}
    assert [value.node_key for value in batch.values] == ["TotW", "Spd"]
    assert [value.value for value in batch.values] == ["1001.0", "1002.0"]
    assert all(value.server_timestamp == observed_at for value in batch.values)


def test_start_subscription_keeps_reader_open_and_maps_micro_batch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now = datetime(2026, 4, 24, 9, 0, tzinfo=UTC)
    fake_reader = FakeReader(
        subscription_batch=SourceDataChangeBatch(
            changes=(
                SourceDataChange(
                    path="ns=2;s=MMXU1.TotW.mag.f",
                    value=1001.0,
                    status="Good",
                    source_timestamp=now,
                    server_timestamp=now,
                    client_sequence=10,
                ),
                SourceDataChange(
                    path="ns=2;s=MMXU1.Spd.mag.f",
                    value=1002.0,
                    status="Good",
                    source_timestamp=now,
                    server_timestamp=now,
                    client_sequence=11,
                ),
            ),
            client_received_at=now,
            client_processed_at=now,
        )
    )
    monkeypatch.setattr(
        adapter_module,
        "OpcUaSourceReader",
        lambda profile: _attach_profile(fake_reader, profile),
    )

    received_batches: list[AcquiredNodeStateBatch] = []

    async def state_received(batch: AcquiredNodeStateBatch) -> None:
        received_batches.append(batch)

    handle = asyncio.run(
        OpcUaSourceAcquisitionAdapter().start_subscription(
            _execution(),
            _connection(),
            _items(),
            state_received=state_received,
        )
    )

    assert isinstance(handle, OpcUaAdapterSubscriptionHandle)
    assert fake_reader.entered == 1
    assert fake_reader.exited == 0
    assert len(received_batches) == 1
    assert [value.node_key for value in received_batches[0].values] == ["TotW", "Spd"]
    assert received_batches[0].attributes == {
        "acquisition_kind": "subscription_datachange"
    }

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

    async def state_received(batch: AcquiredNodeStateBatch) -> None:
        del batch

    with pytest.raises(RuntimeError, match="subscribe failed"):
        asyncio.run(
            OpcUaSourceAcquisitionAdapter().start_subscription(
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
