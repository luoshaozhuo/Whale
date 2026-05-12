"""Unit tests for OPC UA source reader helpers."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any

import pytest
from asyncua import ua  # type: ignore[import-untyped]

from tools.source_simulation.adapters.opcua.source_reader import OpcUaSourceReader
from tools.source_simulation.domain import SourceConnection, SourceNodeInfo, SourceReadPoint


class _FakeNodeId:
    def __init__(self, value: str) -> None:
        self._value = value

    def to_string(self) -> str:
        return self._value


class _FakeNode:
    def __init__(
        self,
        node_id: str,
        node_class: object,
        *,
        children: list["_FakeNode"] | None = None,
    ) -> None:
        self.nodeid = _FakeNodeId(node_id)
        self._node_class = node_class
        self._children = children or []
        self._data_type = type("DataType", (), {"Identifier": 11})()

    async def get_children(self) -> list["_FakeNode"]:
        return self._children

    async def read_node_class(self) -> object:
        return self._node_class

    async def read_data_type(self) -> object:
        return self._data_type


class _FakeObjectsNode:
    def __init__(self, windfarm: _FakeNode) -> None:
        self._windfarm = windfarm

    async def get_child(self, path: str) -> _FakeNode:
        assert path == "2:WindFarm"
        return self._windfarm


class _FakeSubscription:
    def __init__(self) -> None:
        self.unsubscribed_handles: object | None = None
        self.deleted = False

    async def subscribe_data_change(self, nodes: list[object]) -> list[int]:
        self.nodes = nodes
        return [11, 22]

    async def unsubscribe(self, handles: object) -> None:
        self.unsubscribed_handles = handles

    async def delete(self) -> None:
        self.deleted = True


class _FakeClient:
    def __init__(self, windfarm: _FakeNode) -> None:
        self.nodes = type("Nodes", (), {"objects": _FakeObjectsNode(windfarm)})()
        self.get_node_calls: list[str] = []
        self.read_values_calls: list[list[object]] = []
        self.read_attributes_calls: list[tuple[list[object], object]] = []
        self.disconnected = False
        self.subscription = _FakeSubscription()

    def get_node(self, node_path: str) -> object:
        self.get_node_calls.append(node_path)
        return SimpleNamespace(node_path=node_path)

    async def read_values(self, nodes: list[object]) -> list[object]:
        self.read_values_calls.append(nodes)
        return [10.5 for _ in nodes]

    async def read_attributes(self, nodes: list[object], *, attr: object) -> list[object]:
        self.read_attributes_calls.append((nodes, attr))
        return [
            SimpleNamespace(
                Value=SimpleNamespace(Value=20.5),
                StatusCode="Good",
                SourceTimestamp="source-ts",
                ServerTimestamp="server-ts",
            )
            for _ in nodes
        ]

    async def disconnect(self) -> None:
        self.disconnected = True

    async def create_subscription(self, interval_ms: int, handler: object) -> _FakeSubscription:
        self.interval_ms = interval_ms
        self.handler = handler
        return self.subscription


def _connection() -> SourceConnection:
    return SourceConnection(
        name="WTG_01",
        ied_name="WTG_01",
        ld_name="LD0",
        host="127.0.0.1",
        port=4840,
        transport="tcp",
        protocol="opcua",
        namespace_uri="urn:test:reader",
        params={"namespace_uri": "urn:test:reader"},
    )


def _windfarm() -> _FakeNode:
    variable_a = _FakeNode("ns=2;s=WTG_01.LD0.MMXU1.TotW", ua.NodeClass.Variable)
    variable_a._data_type = type("DataType", (), {"Identifier": 11})()  # noqa: SLF001
    variable_b = _FakeNode("ns=2;s=WTG_01.LD0.GGIO1.TurSt", ua.NodeClass.Variable)
    variable_b._data_type = type("DataType", (), {"Identifier": 1})()  # noqa: SLF001
    folder = _FakeNode("ns=2;s=WTG_01", ua.NodeClass.Object, children=[variable_a, variable_b])
    return _FakeNode("ns=2;s=WindFarm", ua.NodeClass.Object, children=[folder])


@pytest.mark.unit
def test_list_nodes_returns_full_node_metadata() -> None:
    reader = OpcUaSourceReader(_connection())
    reader._client = _FakeClient(_windfarm())  # noqa: SLF001
    reader._nsidx = 2  # noqa: SLF001

    result = asyncio.run(reader.list_nodes())

    assert result == (
        SourceNodeInfo(
            node_path="ns=2;s=WTG_01.LD0.MMXU1.TotW",
            data_type="FLOAT64",
            ld_name="LD0",
            ln_name="MMXU1",
            do_name="TotW",
        ),
        SourceNodeInfo(
            node_path="ns=2;s=WTG_01.LD0.GGIO1.TurSt",
            data_type="BOOLEAN",
            ld_name="LD0",
            ln_name="GGIO1",
            do_name="TurSt",
        ),
    )


@pytest.mark.unit
def test_list_readable_variable_nodes_returns_all_variable_node_ids() -> None:
    reader = OpcUaSourceReader(_connection())
    reader._client = _FakeClient(_windfarm())  # noqa: SLF001
    reader._nsidx = 2  # noqa: SLF001

    result = asyncio.run(reader.list_readable_variable_nodes())

    assert result == (
        ("ns=2;s=WTG_01.LD0.MMXU1.TotW", "FLOAT64"),
        ("ns=2;s=WTG_01.LD0.GGIO1.TurSt", "BOOLEAN"),
    )


@pytest.mark.unit
def test_list_readable_variable_nodes_requires_namespace_index() -> None:
    reader = OpcUaSourceReader(_connection())
    reader._client = _FakeClient(_FakeNode("ns=2;s=WindFarm", ua.NodeClass.Object))  # noqa: SLF001

    with pytest.raises(RuntimeError, match="Namespace index is not initialized"):
        asyncio.run(reader.list_readable_variable_nodes())


@pytest.mark.unit
def test_get_nodes_reuses_cached_nodes_within_one_reader_session() -> None:
    reader = OpcUaSourceReader(_connection())
    client = _FakeClient(_windfarm())
    reader._client = client  # noqa: SLF001

    first_nodes = reader._get_nodes(["ns=1;s=A", "ns=1;s=A"])  # noqa: SLF001
    second_nodes = reader._get_nodes(["ns=1;s=A"])  # noqa: SLF001

    assert len(first_nodes) == 2
    assert first_nodes[0] is first_nodes[1]
    assert second_nodes[0] is first_nodes[0]
    assert client.get_node_calls == ["ns=1;s=A"]


@pytest.mark.unit
def test_aexit_clears_node_cache_even_after_disconnect() -> None:
    reader = OpcUaSourceReader(_connection())
    client = _FakeClient(_windfarm())
    reader._client = client  # noqa: SLF001
    reader._nsidx = 2  # noqa: SLF001
    reader._node_cache["ns=1;s=A"] = SimpleNamespace(node_path="ns=1;s=A")  # noqa: SLF001

    asyncio.run(reader.__aexit__(None, None, None))

    assert client.disconnected is True
    assert reader._client is None  # noqa: SLF001
    assert reader._nsidx is None  # noqa: SLF001
    assert reader._node_cache == {}  # noqa: SLF001


@pytest.mark.unit
def test_read_uses_read_values_in_fast_mode_and_reuses_cached_nodes() -> None:
    reader = OpcUaSourceReader(_connection())
    client = _FakeClient(_windfarm())
    reader._client = client  # noqa: SLF001
    reader._nsidx = 2  # noqa: SLF001

    first_batch = asyncio.run(reader.read(["s=WTG_01.LD0.MMXU1.TotW"], fast_mode=True))
    second_batch = asyncio.run(reader.read(["s=WTG_01.LD0.MMXU1.TotW"], fast_mode=True))

    assert client.get_node_calls == ["ns=2;s=WTG_01.LD0.MMXU1.TotW"]
    assert len(client.read_values_calls) == 2
    assert first_batch == (
        SourceReadPoint(
            path="ns=2;s=WTG_01.LD0.MMXU1.TotW",
            value=10.5,
            status=None,
            source_timestamp=None,
            server_timestamp=None,
        ),
    )
    assert second_batch[0].path == "ns=2;s=WTG_01.LD0.MMXU1.TotW"


@pytest.mark.unit
def test_read_uses_read_attributes_in_non_fast_mode_and_keeps_metadata() -> None:
    reader = OpcUaSourceReader(_connection())
    client = _FakeClient(_windfarm())
    reader._client = client  # noqa: SLF001
    reader._nsidx = 2  # noqa: SLF001

    batch = asyncio.run(reader.read(["s=WTG_01.LD0.MMXU1.TotW"], fast_mode=False))

    assert client.get_node_calls == ["ns=2;s=WTG_01.LD0.MMXU1.TotW"]
    assert client.read_attributes_calls == [
        (
            [reader._node_cache["ns=2;s=WTG_01.LD0.MMXU1.TotW"]],
            ua.AttributeIds.Value,
        )  # noqa: SLF001
    ]
    assert batch[0].path == "ns=2;s=WTG_01.LD0.MMXU1.TotW"
    assert batch[0].value == 20.5
    assert batch[0].status == "Good"
    assert batch[0].source_timestamp is None
    assert batch[0].server_timestamp is None


@pytest.mark.unit
def test_start_subscription_reuses_cached_nodes_for_subscription_path() -> None:
    async def _run() -> None:
        reader = OpcUaSourceReader(_connection())
        client = _FakeClient(_windfarm())
        reader._client = client  # noqa: SLF001
        reader._nsidx = 2  # noqa: SLF001

        handle = await reader.start_subscription(
            ["s=WTG_01.LD0.MMXU1.TotW", "s=WTG_01.LD0.MMXU1.TotW"],
            interval_ms=100,
            on_data_change=lambda node, val, data: None,
        )
        await handle.close()

        assert client.get_node_calls == ["ns=2;s=WTG_01.LD0.MMXU1.TotW"]
        assert client.subscription.nodes[0] is client.subscription.nodes[1]
        assert client.subscription.unsubscribed_handles == [11, 22]
        assert client.subscription.deleted is True

    asyncio.run(_run())
