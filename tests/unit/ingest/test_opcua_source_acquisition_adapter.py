"""Unit tests for the OPC UA source-acquisition adapter."""

from __future__ import annotations

import asyncio

import pytest

from whale.ingest.adapters.source import opcua_source_acquisition_adapter as adapter_module
from whale.ingest.adapters.source.opcua_source_acquisition_adapter import (
    OpcUaSourceAcquisitionAdapter,
)
from whale.ingest.usecases.dtos.acquisition_item_data import AcquisitionItemData
from whale.ingest.usecases.dtos.source_acquisition_request import (
    SourceAcquisitionRequest,
)
from whale.ingest.usecases.dtos.source_connection_data import SourceConnectionData
from whale.ingest.usecases.dtos.source_subscription_request import (
    SourceSubscriptionRequest,
)


class FakeNode:
    """Fake OPC UA node used by the adapter test."""

    def __init__(self, node_id: str) -> None:
        """Store the resolved node id."""
        self.node_id = node_id


class FakeClient:
    """Fake OPC UA client used by the adapter test."""

    def __init__(self, endpoint: str) -> None:
        """Store the connected endpoint and requested node addresses."""
        self.endpoint = endpoint
        self.requested_nodes: list[str] = []

    async def __aenter__(self) -> "FakeClient":
        """Return the fake client from the context manager."""
        return self

    async def __aexit__(self, exc_type: object, exc: object, tb: object) -> None:
        """Close the fake context manager."""
        del exc_type, exc, tb

    def get_node(self, address: str) -> FakeNode:
        """Capture the address and return one fake node object."""
        self.requested_nodes.append(address)
        return FakeNode(address)

    async def read_values(self, nodes: list[FakeNode]) -> list[object]:
        """Return synthetic values for the requested nodes."""
        values = {
            "nsu=urn:windfarm:2wtg;s=WTG_01.TotW": 1200.0,
            "nsu=urn:windfarm:2wtg;s=WTG_01.Spd": 12.5,
            "ns=2;s=WTG_01.TotW": 1200.0,
            "ns=2;s=WTG_01.Spd": 12.5,
        }
        return [values[node.node_id] for node in nodes]

    async def get_namespace_index(self, namespace_uri: str) -> int:
        """Return the synthetic namespace index for the expected URI."""
        assert namespace_uri == "urn:windfarm:2wtg"
        return 2


def test_read_reads_each_item_address_without_hard_coded_node_rules(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Read each configured item address and map it to one acquired node state."""
    fake_client = FakeClient("opc.tcp://127.0.0.1:4840")
    monkeypatch.setattr(adapter_module, "Client", lambda endpoint: fake_client)
    adapter = OpcUaSourceAcquisitionAdapter()

    states = asyncio.run(
        adapter.read(
            SourceAcquisitionRequest(
                source_id="WTG_01",
                connection=SourceConnectionData(
                    endpoint="opc.tcp://127.0.0.1:4840",
                    params={"security_policy": "None", "security_mode": "None"},
                ),
                items=[
                    AcquisitionItemData(
                        key="TotW",
                        locator="nsu=urn:windfarm:2wtg;s=WTG_01.TotW",
                    ),
                    AcquisitionItemData(
                        key="Spd",
                        locator="nsu=urn:windfarm:2wtg;s=WTG_01.Spd",
                    ),
                ],
            )
        )
    )

    assert fake_client.requested_nodes == [
        "nsu=urn:windfarm:2wtg;s=WTG_01.TotW",
        "nsu=urn:windfarm:2wtg;s=WTG_01.Spd",
    ]
    assert [state.node_key for state in states] == ["TotW", "Spd"]
    assert [state.node_id for state in states] == fake_client.requested_nodes
    assert [state.value for state in states] == ["1200.0", "12.5"]


def test_read_resolves_namespace_uri_when_item_uses_address_suffix(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Resolve one namespace-specific node id from namespace URI plus item address."""
    fake_client = FakeClient("opc.tcp://127.0.0.1:4840")
    monkeypatch.setattr(adapter_module, "Client", lambda endpoint: fake_client)
    adapter = OpcUaSourceAcquisitionAdapter()

    states = asyncio.run(
        adapter.read(
            SourceAcquisitionRequest(
                source_id="WTG_01",
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
                        locator="s=WTG_01.TotW",
                    ),
                    AcquisitionItemData(
                        key="Spd",
                        locator="s=WTG_01.Spd",
                    ),
                ],
            )
        )
    )

    assert fake_client.requested_nodes == ["ns=2;s=WTG_01.TotW", "ns=2;s=WTG_01.Spd"]
    assert [state.node_id for state in states] == fake_client.requested_nodes


def test_subscribe_returns_when_stop_is_requested() -> None:
    """Stop subscription acquisition when the runtime stop callback is set."""
    adapter = OpcUaSourceAcquisitionAdapter()
    stop_checks = 0

    def stop_requested() -> bool:
        nonlocal stop_checks
        stop_checks += 1
        return True

    asyncio.run(
        adapter.subscribe(
            SourceSubscriptionRequest(
                source_id="WTG_01",
                connection=SourceConnectionData(
                    endpoint="opc.tcp://127.0.0.1:4840",
                    params={"security_policy": "None", "security_mode": "None"},
                ),
                items=[],
                stop_requested=stop_requested,
            )
        )
    )

    assert stop_checks == 1
