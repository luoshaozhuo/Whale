"""Unit tests for the shared OPC UA source reader."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from asyncua import ua  # type: ignore[import-untyped]

from whale.shared.source.models import SourceConnectionProfile
from whale.shared.source.opcua.reader import OpcUaSourceReader


class _FakeClient:
    def __init__(self, data_values: list[object]) -> None:
        self._data_values = data_values

    async def read_attributes(self, nodes: list[object], *, attr: object) -> list[object]:
        del nodes
        assert attr == ua.AttributeIds.Value
        return self._data_values


@pytest.mark.unit
def test_read_attributes_keeps_naive_timestamps_unchanged() -> None:
    naive_timestamp = datetime(2026, 5, 11, 12, 34, 56)
    reader = OpcUaSourceReader(
        SourceConnectionProfile(
            endpoint="opcua.tcp://127.0.0.1:4840",
        )
    )
    reader._client = _FakeClient(  # noqa: SLF001
        [
            SimpleNamespace(
                Value=SimpleNamespace(Value=20.5),
                StatusCode="Good",
                SourceTimestamp=naive_timestamp,
                ServerTimestamp=naive_timestamp,
            )
        ]
    )
    reader._node_cache["ns=1;s=MMXU1.TotW.mag.f"] = object()  # noqa: SLF001

    batch = asyncio.run(
        reader.read(["ns=1;s=MMXU1.TotW.mag.f"], include_metadata=True)
    )

    assert batch[0].source_timestamp is naive_timestamp
    assert batch[0].server_timestamp is naive_timestamp


@pytest.mark.unit
def test_read_attributes_keeps_aware_utc_timestamps_unchanged() -> None:
    aware_timestamp = datetime(2026, 5, 11, 12, 34, 56, tzinfo=UTC)
    reader = OpcUaSourceReader(
        SourceConnectionProfile(
            endpoint="opcua.tcp://127.0.0.1:4840",
        )
    )
    reader._client = _FakeClient(  # noqa: SLF001
        [
            SimpleNamespace(
                Value=SimpleNamespace(Value=20.5),
                StatusCode="Good",
                SourceTimestamp=aware_timestamp,
                ServerTimestamp=aware_timestamp,
            )
        ]
    )
    reader._node_cache["ns=1;s=MMXU1.TotW.mag.f"] = object()  # noqa: SLF001

    batch = asyncio.run(
        reader.read(["ns=1;s=MMXU1.TotW.mag.f"], include_metadata=True)
    )

    assert batch[0].source_timestamp is aware_timestamp
    assert batch[0].server_timestamp is aware_timestamp
