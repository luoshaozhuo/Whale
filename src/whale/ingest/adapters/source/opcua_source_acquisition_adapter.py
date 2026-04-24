"""Minimal OPC UA acquisition adapter for ingest."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime

from asyncua import Client  # type: ignore[import-untyped]

from whale.ingest.ports.source.source_acquisition_port import SourceAcquisitionPort
from whale.ingest.usecases.dtos.acquired_node_state import AcquiredNodeState
from whale.ingest.usecases.dtos.source_acquisition_request import (
    SourceAcquisitionRequest,
)
from whale.ingest.usecases.dtos.source_subscription_request import (
    SourceSubscriptionRequest,
)


class OpcUaSourceAcquisitionAdapter(SourceAcquisitionPort):
    """Provide the minimal read acquisition interface for OPC UA."""

    async def read(self, request: SourceAcquisitionRequest) -> list[AcquiredNodeState]:
        """Return one acquisition batch for the configured source."""
        observed_at = datetime.now(tz=UTC)
        if request.connection.endpoint is None:
            raise ValueError("OPC UA acquisition requires a connection endpoint.")

        async with Client(request.connection.endpoint) as client:
            node_ids = await self._resolve_node_ids(client, request)
            nodes = [client.get_node(node_id) for node_id in node_ids]
            values = await client.read_values(nodes)

        return [
            AcquiredNodeState(
                source_id=request.source_id,
                node_key=item.key,
                node_id=node_id,
                value=str(value),
                observed_at=observed_at,
            )
            for item, node_id, value in zip(request.items, node_ids, values, strict=True)
        ]

    async def subscribe(self, request: SourceSubscriptionRequest) -> None:
        """Start subscription-based acquisition for the configured source."""
        if request.stop_requested is None:
            raise ValueError("Subscription request must provide a stop callback.")

        while not request.stop_requested():
            await asyncio.sleep(0.1)

    async def _resolve_node_ids(
        self,
        client: Client,
        request: SourceAcquisitionRequest,
    ) -> list[str]:
        """Resolve all item addresses into concrete OPC UA node ids."""
        namespace_indexes: dict[str, int] = {}
        namespace_uri = request.connection.params.get("namespace_uri")
        node_ids: list[str] = []

        for item in request.items:
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
