"""Unit tests for the OPC UA source-acquisition adapter."""

from __future__ import annotations

from whale.ingest.adapters.source.opcua_source_acquisition_adapter import (
    OpcUaSourceAcquisitionAdapter,
)
from whale.ingest.usecases.dtos.acquisition_item_data import AcquisitionItemData
from whale.ingest.usecases.dtos.source_acquisition_request import (
    SourceAcquisitionRequest,
)
from whale.ingest.usecases.dtos.source_connection_data import SourceConnectionData


class FakeNode:
    """Fake OPC UA node used by the adapter test."""

    def __init__(self, value: object) -> None:
        """Store the value returned by `read_value`."""
        self._value = value

    def read_value(self) -> object:
        """Return the configured node value."""
        return self._value


class FakeClient:
    """Fake OPC UA client used by the adapter test."""

    def __init__(self, endpoint: str) -> None:
        """Store the connected endpoint and requested node addresses."""
        self.endpoint = endpoint
        self.requested_nodes: list[str] = []

    def __enter__(self) -> "FakeClient":
        """Return the fake client from the context manager."""
        return self

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        """Close the fake context manager."""
        del exc_type, exc, tb

    def get_node(self, address: str) -> FakeNode:
        """Capture the address and return a node with one synthetic value."""
        self.requested_nodes.append(address)
        values = {
            "nsu=urn:windfarm:2wtg;s=WTG_01.TotW": 1200.0,
            "nsu=urn:windfarm:2wtg;s=WTG_01.Spd": 12.5,
            "ns=2;s=WTG_01.TotW": 1200.0,
            "ns=2;s=WTG_01.Spd": 12.5,
        }
        return FakeNode(values[address])

    def get_namespace_index(self, namespace_uri: str) -> int:
        """Return the synthetic namespace index for the expected URI."""
        assert namespace_uri == "urn:windfarm:2wtg"
        return 2


def test_read_once_reads_each_item_address_without_hard_coded_node_rules() -> None:
    """Read each configured item address and map it to one acquired node state."""
    fake_client = FakeClient("opc.tcp://127.0.0.1:4840")
    adapter = OpcUaSourceAcquisitionAdapter(client_factory=lambda endpoint: fake_client)

    states = adapter.read_once(
        SourceAcquisitionRequest(
            runtime_config_id=101,
            source_id="WTG_01",
            source_name="WTG_01",
            protocol="opcua",
            connection=SourceConnectionData(
                endpoint="opc.tcp://127.0.0.1:4840",
                security_policy="None",
                security_mode="None",
                update_interval_ms=100,
            ),
            items=[
                AcquisitionItemData(
                    key="TotW",
                    address="nsu=urn:windfarm:2wtg;s=WTG_01.TotW",
                ),
                AcquisitionItemData(
                    key="Spd",
                    address="nsu=urn:windfarm:2wtg;s=WTG_01.Spd",
                ),
            ],
        )
    )

    assert fake_client.requested_nodes == [
        "nsu=urn:windfarm:2wtg;s=WTG_01.TotW",
        "nsu=urn:windfarm:2wtg;s=WTG_01.Spd",
    ]
    assert [state.node_key for state in states] == ["TotW", "Spd"]
    assert [state.node_id for state in states] == fake_client.requested_nodes
    assert [state.value for state in states] == ["1200.0", "12.5"]


def test_read_once_resolves_namespace_uri_when_item_uses_address_suffix() -> None:
    """Resolve one namespace-specific node id from namespace URI plus item address."""
    fake_client = FakeClient("opc.tcp://127.0.0.1:4840")
    adapter = OpcUaSourceAcquisitionAdapter(client_factory=lambda endpoint: fake_client)

    states = adapter.read_once(
        SourceAcquisitionRequest(
            runtime_config_id=101,
            source_id="WTG_01",
            source_name="WTG_01",
            protocol="opcua",
            connection=SourceConnectionData(
                endpoint="opc.tcp://127.0.0.1:4840",
                security_policy="None",
                security_mode="None",
                update_interval_ms=100,
            ),
            items=[
                AcquisitionItemData(
                    key="TotW",
                    address="s=WTG_01.TotW",
                    namespace_uri="urn:windfarm:2wtg",
                ),
                AcquisitionItemData(
                    key="Spd",
                    address="s=WTG_01.Spd",
                    namespace_uri="urn:windfarm:2wtg",
                ),
            ],
        )
    )

    assert fake_client.requested_nodes == ["ns=2;s=WTG_01.TotW", "ns=2;s=WTG_01.Spd"]
    assert [state.node_id for state in states] == fake_client.requested_nodes
