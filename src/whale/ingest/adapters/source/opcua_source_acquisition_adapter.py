"""Minimal OPC UA acquisition adapter for ingest."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime

from asyncua.sync import Client  # type: ignore[import-untyped]

from whale.ingest.ports.source.source_acquisition_port import SourceAcquisitionPort
from whale.ingest.usecases.dtos.acquired_node_state import AcquiredNodeState
from whale.ingest.usecases.dtos.source_acquisition_request import (
    SourceAcquisitionRequest,
)
from whale.ingest.usecases.dtos.source_subscription_request import (
    SourceSubscriptionRequest,
)


class OpcUaSourceAcquisitionAdapter(SourceAcquisitionPort):
    """Provide the minimal read-once acquisition interface for OPC UA."""

    def __init__(self, client_factory: Callable[[str], Client] = Client) -> None:
        """Store the client factory used to connect to OPC UA endpoints."""
        self._client_factory = client_factory

    def read_once(self, request: SourceAcquisitionRequest) -> list[AcquiredNodeState]:
        """Return one acquisition batch for the configured source."""
        observed_at = datetime.now(tz=UTC)

        with self._client_factory(request.connection.endpoint) as client:
            states: list[AcquiredNodeState] = []
            for item in request.items:
                node_id = self._resolve_node_id(client, item.address, item.namespace_uri)
                states.append(
                    AcquiredNodeState(
                        source_id=request.source_id,
                        node_key=item.key,
                        node_id=node_id,
                        value=str(client.get_node(node_id).read_value()),
                        quality=None,
                        observed_at=observed_at,
                    )
                )
            return states

    def subscribe(self, request: SourceSubscriptionRequest) -> None:
        """Start subscription-based acquisition for the configured source."""
        _ = request
        raise NotImplementedError("OPC UA subscription is not implemented yet.")

    @staticmethod
    def _resolve_node_id(client: Client, address: str, namespace_uri: str | None) -> str:
        """Resolve one item address into the concrete node id understood by asyncua."""
        if address.startswith(("ns=", "nsu=")):
            return address
        if namespace_uri is None:
            return address
        namespace_index = client.get_namespace_index(namespace_uri)
        return f"ns={namespace_index};{address}"
