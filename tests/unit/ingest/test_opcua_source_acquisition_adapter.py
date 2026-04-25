"""Unit tests for the OPC UA source-acquisition adapter."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Any

import pytest

from whale.ingest.adapters.source import opcua_source_acquisition_adapter as adapter_module
from whale.ingest.adapters.source.opcua_source_acquisition_adapter import (
    OpcUaSourceAcquisitionAdapter,
)
from whale.ingest.usecases.dtos.acquired_node_state import AcquiredNodeState
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
        self.nodeid = node_id


class FakeDataValue:
    """Fake monitored value used by the subscription payload."""

    def __init__(self, source_timestamp: datetime) -> None:
        """Store the synthetic source timestamp."""
        self.SourceTimestamp = source_timestamp


class FakeMonitoredItem:
    """Fake monitored-item wrapper for the subscription payload."""

    def __init__(self, source_timestamp: datetime) -> None:
        """Store the synthetic monitored value."""
        self.Value = FakeDataValue(source_timestamp)


class FakeDataChange:
    """Fake data-change payload passed to the subscription handler."""

    def __init__(self, source_timestamp: datetime) -> None:
        """Store the monitored item wrapper."""
        self.monitored_item = FakeMonitoredItem(source_timestamp)


class FakeSubscription:
    """Fake OPC UA subscription used by the adapter test."""

    def __init__(self, handler: Any) -> None:
        """Store the notification handler and capture lifecycle calls."""
        self.handler = handler
        self.unsubscribed_handles: list[int] = []
        self.deleted = False
        self._next_handle = 1

    async def subscribe_data_change(self, nodes: FakeNode | list[FakeNode]) -> list[int]:
        """Subscribe all nodes and emit one synthetic notification per node."""
        node_list = nodes if isinstance(nodes, list) else [nodes]
        timestamp = datetime(2026, 4, 24, 9, 0, tzinfo=UTC)
        handles: list[int] = []
        for node in node_list:
            handle = self._next_handle
            self._next_handle += 1
            handles.append(handle)
            await self.handler.datachange_notification(
                node,
                1000.0 + handle,
                FakeDataChange(timestamp),
            )
        return handles

    async def unsubscribe(self, handle: int) -> None:
        """Capture subscription handle cleanup."""
        self.unsubscribed_handles.append(handle)

    async def delete(self) -> None:
        """Capture subscription deletion."""
        self.deleted = True


class FakeClient:
    """Fake OPC UA client used by the adapter test."""

    def __init__(self, endpoint: str) -> None:
        """Store the connected endpoint and requested node addresses."""
        self.endpoint = endpoint
        self.requested_nodes: list[str] = []
        self.subscription: FakeSubscription | None = None
        self.publishing_interval_ms: int | None = None

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

    async def create_subscription(
        self, publishing_interval_ms: int, handler: object
    ) -> FakeSubscription:
        """Create one fake subscription and capture the publishing interval."""
        self.publishing_interval_ms = publishing_interval_ms
        self.subscription = FakeSubscription(handler)
        return self.subscription


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
    assert [state.node_key for state in states] == ["TotW", "Spd"]


def test_read_builds_endpoint_from_host_and_port(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Build the OPC UA endpoint from host and port when endpoint is omitted."""
    fake_client = FakeClient("opc.tcp://127.0.0.1:4840")
    monkeypatch.setattr(adapter_module, "Client", lambda endpoint: fake_client)
    adapter = OpcUaSourceAcquisitionAdapter()

    states = asyncio.run(
        adapter.read(
            SourceAcquisitionRequest(
                source_id="WTG_01",
                connection=SourceConnectionData(
                    host="127.0.0.1",
                    port=4840,
                    params={"security_policy": "None", "security_mode": "None"},
                ),
                items=[
                    AcquisitionItemData(
                        key="TotW",
                        locator="nsu=urn:windfarm:2wtg;s=WTG_01.TotW",
                    ),
                ],
            )
        )
    )

    assert fake_client.endpoint == "opc.tcp://127.0.0.1:4840"
    assert [state.node_key for state in states] == ["TotW"]


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
                state_received=_capture_states,
            )
        )
    )

    assert stop_checks == 1


async def _capture_states(states: object) -> None:
    """Ignore subscription states in tests that only exercise shutdown behavior."""
    del states


def test_subscribe_subscribes_all_items_and_emits_states(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Subscribe all configured items in one OPC UA subscription and emit updates."""
    fake_client = FakeClient("opc.tcp://127.0.0.1:4840")
    monkeypatch.setattr(adapter_module, "Client", lambda endpoint: fake_client)
    adapter = OpcUaSourceAcquisitionAdapter()
    received_states: list[AcquiredNodeState] = []

    async def state_received(states: list[AcquiredNodeState]) -> None:
        received_states.extend(states)

    asyncio.run(
        adapter.subscribe(
            SourceSubscriptionRequest(
                source_id="WTG_01",
                connection=SourceConnectionData(
                    endpoint="opc.tcp://127.0.0.1:4840",
                    params={
                        "security_policy": "None",
                        "security_mode": "None",
                        "namespace_uri": "urn:windfarm:2wtg",
                        "publishing_interval_ms": 250,
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
                stop_requested=lambda: len(received_states) >= 2,
                state_received=state_received,
            )
        )
    )

    assert fake_client.requested_nodes == ["ns=2;s=WTG_01.TotW", "ns=2;s=WTG_01.Spd"]
    assert fake_client.publishing_interval_ms == 250
    assert [state.node_key for state in received_states] == ["TotW", "Spd"]
    assert [state.value for state in received_states] == ["1001.0", "1002.0"]
    assert fake_client.subscription is not None
    assert fake_client.subscription.unsubscribed_handles == [1, 2]
    assert fake_client.subscription.deleted is True
