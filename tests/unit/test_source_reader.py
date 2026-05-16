"""Unit tests for the shared OPC UA source reader skeleton."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

import pytest
from asyncua import ua  # type: ignore[import-untyped]

from whale.shared.source.models import Batch, SourceConnectionProfile, SourceNodeInfo
from whale.shared.source.opcua.reader import (
    OpcUaSourceReader,
    OpcUaSubscriptionHandle,
    RawOpcUaReadResult,
)


class _FakeNodeId:
    def __init__(self, value: str) -> None:
        self._value = value

    def to_string(self) -> str:
        return self._value


class _FakeBrowseNode:
    def __init__(
        self,
        node_id: str,
        node_class: object,
        *,
        children: list["_FakeBrowseNode"] | None = None,
        data_type_identifier: int = 11,
    ) -> None:
        self.nodeid = _FakeNodeId(node_id)
        self._node_class = node_class
        self._children = children or []
        self._data_type = SimpleNamespace(Identifier=data_type_identifier)

    async def get_children(self) -> list["_FakeBrowseNode"]:
        return self._children

    async def read_node_class(self) -> object:
        return self._node_class

    async def read_data_type(self) -> object:
        return self._data_type


class _FakeObjectsNode:
    def __init__(self, root: _FakeBrowseNode, *, nsidx: int) -> None:
        self._root = root
        self._browse_key = f"{nsidx}:WindFarm"

    async def get_child(self, path: str) -> _FakeBrowseNode:
        if path != self._browse_key:
            raise RuntimeError("child not found")
        return self._root


class _FakeSubscription:
    def __init__(self) -> None:
        self.nodes: list[object] = []
        self.unsubscribed_handles: list[int] | None = None
        self.deleted = False

    async def subscribe_data_change(self, nodes: list[object]) -> list[int]:
        self.nodes = nodes
        return [11, 22]

    async def unsubscribe(self, handles: list[int]) -> None:
        self.unsubscribed_handles = handles

    async def delete(self) -> None:
        self.deleted = True


class _FakeClient:
    def __init__(
        self,
        *,
        values: list[object] | None = None,
        data_values: list[object] | None = None,
        read_error: Exception | None = None,
        browse_root: _FakeBrowseNode | None = None,
        nsidx: int = 2,
    ) -> None:
        self._values = values or []
        self._data_values = data_values or []
        self._read_error = read_error
        self.get_node_calls: list[str] = []
        self.read_values_calls: list[list[object]] = []
        self.read_attributes_calls: list[tuple[list[object], object]] = []
        self.disconnect_calls = 0
        self.created_subscription = _FakeSubscription()
        self.created_interval_ms: int | None = None
        self.created_handler: object | None = None
        root = browse_root or _FakeBrowseNode("ns=2;s=Objects", "Object")
        self.nodes = SimpleNamespace(objects=_FakeObjectsNode(root, nsidx=nsidx))

    def get_node(self, node_path: str) -> object:
        self.get_node_calls.append(node_path)
        return SimpleNamespace(node_path=node_path)

    async def read_values(self, nodes: list[object]) -> list[object]:
        self.read_values_calls.append(nodes)
        if self._read_error is not None:
            raise self._read_error
        return self._values

    async def read_attributes(self, nodes: list[object], *, attr: object) -> list[object]:
        self.read_attributes_calls.append((nodes, attr))
        if self._read_error is not None:
            raise self._read_error
        return self._data_values

    async def create_subscription(self, interval_ms: int, handler: object) -> _FakeSubscription:
        self.created_interval_ms = interval_ms
        self.created_handler = handler
        return self.created_subscription

    async def disconnect(self) -> None:
        self.disconnect_calls += 1


def _connection() -> SourceConnectionProfile:
    return SourceConnectionProfile(
        endpoint="opc.tcp://127.0.0.1:4840",
        namespace_uri="urn:test:reader",
        timeout_seconds=0.01,
    )


@pytest.mark.unit
def test_read_value_only_returns_batch_with_valid_availability_status() -> None:
    """Return a VALID batch in value_only mode and mark changes as value-only payloads."""
    reader = OpcUaSourceReader(_connection())
    reader._client = _FakeClient(values=[10.5])  # noqa: SLF001
    reader._nsidx = 2  # noqa: SLF001

    batch = asyncio.run(reader.read(["s=WTG_01.LD0.MMXU1.TotW"], mode="value_only"))

    assert batch.availability_status == "VALID"
    assert batch.changes[0].node_key == "ns=2;s=WTG_01.LD0.MMXU1.TotW"
    assert batch.changes[0].value == 10.5
    assert batch.changes[0].attributes == {"value_only": True}


@pytest.mark.unit
def test_read_full_preserves_batch_fields_and_timestamps() -> None:
    """Return a full batch with metadata fields preserved on each NodeValueChange."""
    observed_at = datetime(2026, 5, 12, 8, 30, tzinfo=UTC)
    reader = OpcUaSourceReader(_connection())
    reader._client = _FakeClient()  # noqa: SLF001
    reader._nsidx = 2  # noqa: SLF001

    async def _fake_read_prepared_raw(plan: object) -> RawOpcUaReadResult:
        return RawOpcUaReadResult(
            ok=True,
            data_values=(
                SimpleNamespace(
                    Value=SimpleNamespace(Value=20.5),
                    StatusCode="Good",
                    SourceTimestamp=observed_at,
                    ServerTimestamp=observed_at,
                ),
            ),
            response_timestamp=observed_at,
        )

    reader.read_prepared_raw = _fake_read_prepared_raw  # type: ignore[method-assign]

    batch = asyncio.run(reader.read(["s=WTG_01.LD0.MMXU1.TotW"], mode="full"))

    assert isinstance(batch, Batch)
    assert batch.availability_status == "VALID"
    assert batch.changes[0].quality == "Good"
    assert batch.changes[0].source_timestamp is observed_at
    assert batch.changes[0].server_timestamp is observed_at


@pytest.mark.unit
def test_read_reuses_cached_nodes_across_calls() -> None:
    """Reuse cached OPC UA node objects so repeated reads do not refetch the same node."""
    reader = OpcUaSourceReader(_connection())
    reader._client = _FakeClient(values=[1.0])  # noqa: SLF001
    reader._nsidx = 2  # noqa: SLF001

    asyncio.run(reader.read(["s=WTG_01.LD0.MMXU1.TotW"], mode="value_only"))
    asyncio.run(reader.read(["s=WTG_01.LD0.MMXU1.TotW"], mode="value_only"))

    assert reader._client.get_node_calls == ["ns=2;s=WTG_01.LD0.MMXU1.TotW"]  # noqa: SLF001


@pytest.mark.unit
def test_read_returns_error_batch_with_retry_metadata_after_failure() -> None:
    """Return an ERROR batch when repeated read attempts fail and expose retry metadata."""
    reader = OpcUaSourceReader(_connection())
    reader._client = _FakeClient(read_error=RuntimeError("boom"))  # noqa: SLF001
    reader._nsidx = 2  # noqa: SLF001

    batch = asyncio.run(reader.read(["s=WTG_01.LD0.MMXU1.TotW"], mode="full"))

    assert batch.changes == ()
    assert batch.availability_status == "ERROR"
    assert batch.attributes["reason"] == "read_failed"
    assert batch.attributes["retry_count"] == 2


@pytest.mark.unit
def test_start_subscription_flushes_baseline_read_before_registering_subscription() -> None:
    """Flush the baseline read batch before returning a live subscription handle."""
    async def _run() -> None:
        observed_batches: list[Batch] = []
        observed_at = datetime(2026, 5, 12, 8, 45, tzinfo=UTC)
        reader = OpcUaSourceReader(_connection())
        reader._client = _FakeClient()  # noqa: SLF001
        reader._nsidx = 2  # noqa: SLF001

        async def _fake_read_prepared_raw(plan: object) -> RawOpcUaReadResult:
            return RawOpcUaReadResult(
                ok=True,
                data_values=(
                    SimpleNamespace(
                        Value=SimpleNamespace(Value=33.0),
                        StatusCode="Good",
                        SourceTimestamp=observed_at,
                        ServerTimestamp=observed_at,
                    ),
                ),
                response_timestamp=observed_at,
            )

        reader.read_prepared_raw = _fake_read_prepared_raw  # type: ignore[method-assign]

        async def _on_data_change(batch: Batch) -> None:
            observed_batches.append(batch)

        handle = await reader.start_subscription(
            ["s=WTG_01.LD0.MMXU1.TotW"],
            interval_ms=250,
            on_data_change=_on_data_change,
        )

        assert isinstance(handle, OpcUaSubscriptionHandle)
        assert len(observed_batches) == 1
        assert observed_batches[0].availability_status == "VALID"
        assert reader._client.created_interval_ms == 250  # noqa: SLF001

        await handle.close()

    asyncio.run(_run())


@pytest.mark.unit
def test_start_subscription_emits_error_batch_when_baseline_read_raises() -> None:
    """Emit an ERROR baseline batch when the initial full read fails before subscription setup."""
    async def _run() -> None:
        observed_batches: list[Batch] = []
        reader = OpcUaSourceReader(_connection())
        reader._client = _FakeClient(read_error=RuntimeError("baseline failed"))  # noqa: SLF001
        reader._nsidx = 2  # noqa: SLF001

        async def _on_data_change(batch: Batch) -> None:
            observed_batches.append(batch)

        handle = await reader.start_subscription(
            ["s=WTG_01.LD0.MMXU1.TotW"],
            interval_ms=250,
            on_data_change=_on_data_change,
        )

        assert len(observed_batches) == 1
        assert observed_batches[0].changes == ()
        assert observed_batches[0].availability_status == "ERROR"
        assert observed_batches[0].attributes["reason"] == "baseline_read_failed"

        await handle.close()

    asyncio.run(_run())


def _build_browse_tree() -> _FakeBrowseNode:
    variable_a = _FakeBrowseNode(
        "ns=2;s=WTG_01.LD0.MMXU1.TotW",
        ua.NodeClass.Variable,
        data_type_identifier=11,
    )
    variable_b = _FakeBrowseNode(
        "ns=2;s=WTG_01.LD0.GGIO1.TurSt",
        ua.NodeClass.Variable,
        data_type_identifier=1,
    )
    folder = _FakeBrowseNode(
        "ns=2;s=WTG_01.LD0",
        ua.NodeClass.Object,
        children=[variable_a, variable_b],
    )
    return _FakeBrowseNode("ns=2;s=WindFarm", ua.NodeClass.Object, children=[folder])


@pytest.mark.unit
def test_list_nodes_returns_server_complete_variable_metadata() -> None:
    """Return complete node metadata from server browse results for every readable variable node."""
    reader = OpcUaSourceReader(_connection())
    reader._client = _FakeClient(browse_root=_build_browse_tree())  # noqa: SLF001
    reader._nsidx = 2  # noqa: SLF001

    node_infos = asyncio.run(reader.list_nodes())

    assert all(isinstance(node, SourceNodeInfo) for node in node_infos)
    assert [node.node_path for node in node_infos] == [
        "ns=2;s=WTG_01.LD0.GGIO1.TurSt",
        "ns=2;s=WTG_01.LD0.MMXU1.TotW",
    ]
    assert [(node.ld_name, node.ln_name, node.do_name) for node in node_infos] == [
        ("LD0", "GGIO1", "TurSt"),
        ("LD0", "MMXU1", "TotW"),
    ]
    assert [node.data_type for node in node_infos] == ["BOOLEAN", "FLOAT64"]


@pytest.mark.unit
def test_list_readable_variable_nodes_returns_path_and_data_type_pairs() -> None:
    """Return browse output as simplified (node_path, data_type) tuples for reader consumers."""
    reader = OpcUaSourceReader(_connection())
    reader._client = _FakeClient(browse_root=_build_browse_tree())  # noqa: SLF001
    reader._nsidx = 2  # noqa: SLF001

    readable_nodes = asyncio.run(reader.list_readable_variable_nodes())

    assert readable_nodes == (
        ("ns=2;s=WTG_01.LD0.GGIO1.TurSt", "BOOLEAN"),
        ("ns=2;s=WTG_01.LD0.MMXU1.TotW", "FLOAT64"),
    )
