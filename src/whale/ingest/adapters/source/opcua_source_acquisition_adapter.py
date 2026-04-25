"""Minimal OPC UA acquisition adapter for ingest."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Any

from asyncua import Client  # type: ignore[import-untyped]

from whale.ingest.ports.source.source_acquisition_port import SourceAcquisitionPort
from whale.ingest.usecases.dtos.acquired_node_state import AcquiredNodeState
from whale.ingest.usecases.dtos.acquisition_item_data import AcquisitionItemData
from whale.ingest.usecases.dtos.source_acquisition_request import (
    SourceAcquisitionRequest,
)
from whale.ingest.usecases.dtos.source_connection_data import SourceConnectionData
from whale.ingest.usecases.dtos.source_subscription_request import (
    SourceSubscriptionRequest,
    SubscriptionStateHandler,
)


class OpcUaSourceAcquisitionAdapter(SourceAcquisitionPort):
    """Provide the minimal read acquisition interface for OPC UA."""

    async def read(self, request: SourceAcquisitionRequest) -> list[AcquiredNodeState]:
        """Return one acquisition batch for the configured source."""
        observed_at = datetime.now(tz=UTC)
        endpoint = self._resolve_endpoint(request.connection)

        async with Client(endpoint) as client:
            node_ids = await self._resolve_node_ids(
                client,
                request.connection,
                request.items,
            )
            nodes = [client.get_node(node_id) for node_id in node_ids]
            values = await client.read_values(nodes)

        return [
            AcquiredNodeState(
                source_id=request.source_id,
                node_key=item.key,
                value=str(value),
                observed_at=observed_at,
            )
            for item, node_id, value in zip(request.items, node_ids, values, strict=True)
        ]

    async def subscribe(self, request: SourceSubscriptionRequest) -> None:
        """Start subscription-based acquisition for the configured source."""
        if request.stop_requested is None:
            raise ValueError("Subscription request must provide a stop callback.")
        if request.state_received is None:
            raise ValueError("Subscription request must provide a state callback.")
        endpoint = self._resolve_endpoint(request.connection)

        if not request.items:
            while not request.stop_requested():
                await asyncio.sleep(0.1)
            return

        async with Client(endpoint) as client:
            node_ids = await self._resolve_node_ids(
                client,
                request.connection,
                request.items,
            )
            nodes = [client.get_node(node_id) for node_id in node_ids]
            handler = _OpcUaSubscriptionHandler(
                source_id=request.source_id,
                node_keys_by_node_id={
                    node_id: item.key for item, node_id in zip(request.items, node_ids, strict=True)
                },
                state_received=request.state_received,
            )
            subscription = await client.create_subscription(
                self._resolve_publishing_interval_ms(request.connection),
                handler,
            )
            handles: list[int] = []
            for node in nodes:
                handles.extend(
                    self._normalize_subscription_handles(
                        await subscription.subscribe_data_change(node)
                    )
                )

            try:
                while not request.stop_requested():
                    await asyncio.sleep(0.1)
            finally:
                for handle in handles:
                    await subscription.unsubscribe(handle)
                await subscription.delete()

    async def _resolve_node_ids(
        self,
        client: Client,
        connection: SourceConnectionData,
        items: list[AcquisitionItemData],
    ) -> list[str]:
        """Resolve all item addresses into concrete OPC UA node ids."""
        namespace_indexes: dict[str, int] = {}
        namespace_uri = connection.params.get("namespace_uri")
        node_ids: list[str] = []

        for item in items:
            node_ids.append(
                await self._resolve_node_id(
                    client,
                    item.locator,
                    namespace_uri if isinstance(namespace_uri, str) else None,
                    namespace_indexes,
                )
            )

        return node_ids

    @staticmethod
    async def _resolve_node_id(
        client: Client,
        address: str,
        namespace_uri: str | None,
        namespace_indexes: dict[str, int],
    ) -> str:
        """Resolve one item address into the concrete node id understood by asyncua."""
        if address.startswith(("ns=", "nsu=")):
            return address
        if namespace_uri is None:
            return address
        namespace_index = namespace_indexes.get(namespace_uri)
        if namespace_index is None:
            namespace_index = await client.get_namespace_index(namespace_uri)
            namespace_indexes[namespace_uri] = namespace_index
        return f"ns={namespace_index};{address}"

    @staticmethod
    def _resolve_publishing_interval_ms(connection: SourceConnectionData) -> int:
        """Return the subscription publishing interval in milliseconds."""
        publishing_interval = connection.params.get("publishing_interval_ms", 100)
        return publishing_interval if isinstance(publishing_interval, int) else 100

    @staticmethod
    def _normalize_subscription_handles(handles: Any) -> list[int]:
        """Normalize asyncua subscription handles into one list."""
        if isinstance(handles, list):
            return [handle for handle in handles if isinstance(handle, int)]
        if isinstance(handles, int):
            return [handles]
        return []

    @staticmethod
    def _resolve_endpoint(connection: SourceConnectionData) -> str:
        """Return one concrete OPC UA endpoint from the available connection fields."""
        if connection.endpoint is not None:
            return connection.endpoint
        if connection.host is None or connection.port is None:
            raise ValueError("OPC UA acquisition requires either endpoint or host and port.")
        return f"opc.tcp://{connection.host}:{connection.port}"


class _OpcUaSubscriptionHandler:
    """Translate OPC UA data-change notifications into acquired node states."""

    def __init__(
        self,
        *,
        source_id: str,
        node_keys_by_node_id: dict[str, str],
        state_received: SubscriptionStateHandler,
    ) -> None:
        """Store the state emission callback and node metadata."""
        self._source_id = source_id
        self._node_keys_by_node_id = dict(node_keys_by_node_id)
        self._state_received = state_received

    async def datachange_notification(self, node: object, val: object, data: object) -> None:
        """Emit one acquired state for each OPC UA data-change notification."""
        node_id = self._resolve_node_id(node)
        node_key = self._node_keys_by_node_id.get(node_id)
        if node_key is None:
            return

        await self._state_received(
            [
                AcquiredNodeState(
                    source_id=self._source_id,
                    node_key=node_key,
                    value=str(val),
                    observed_at=self._resolve_observed_at(data),
                )
            ]
        )

    @staticmethod
    def _resolve_node_id(node: object) -> str:
        """Extract one stable string node id from the asyncua node object."""
        node_id = getattr(node, "nodeid", node)
        return str(node_id)

    @staticmethod
    def _resolve_observed_at(data: object) -> datetime:
        """Extract the source timestamp from one OPC UA notification payload."""
        monitored_item = getattr(data, "monitored_item", None)
        value = getattr(monitored_item, "Value", None)
        source_timestamp = getattr(value, "SourceTimestamp", None)
        if isinstance(source_timestamp, datetime):
            return (
                source_timestamp.replace(tzinfo=UTC)
                if source_timestamp.tzinfo is None
                else source_timestamp.astimezone(UTC)
            )
        return datetime.now(tz=UTC)
