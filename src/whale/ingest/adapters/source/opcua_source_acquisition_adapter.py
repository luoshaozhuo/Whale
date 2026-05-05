"""OPC UA acquisition adapter — resolves endpoint and node IDs internally."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Any

from asyncua import Client  # type: ignore[import-untyped]

from whale.ingest.ports.source.source_acquisition_port import SourceAcquisitionPort
from whale.ingest.usecases.dtos.acquired_node_state import AcquiredNodeState
from whale.ingest.usecases.dtos.source_acquisition_request import (
    SourceAcquisitionRequest,
)
from whale.ingest.usecases.dtos.source_subscription_request import (
    SourceSubscriptionRequest,
    SubscriptionStateHandler,
)


class OpcUaSourceAcquisitionAdapter(SourceAcquisitionPort):
    """Execute OPC UA read / subscribe.

    Accepts pre-resolved *resolved_endpoint* / *resolved_node_ids* when
    available.  When they are missing the adapter resolves them from the
    generic request DTOs — callers do not need to know OPC UA details.
    """

    # ── Public interface ────────────────────────────────────────────

    async def read(self, request: SourceAcquisitionRequest) -> list[AcquiredNodeState]:
        observed_at = datetime.now(tz=UTC)
        endpoint = self._resolve_endpoint(request)
        if not endpoint:
            raise ValueError("Cannot resolve OPC UA endpoint.")

        node_ids = self._resolve_node_ids(request)
        if not node_ids:
            raise ValueError("Cannot resolve OPC UA node IDs.")

        timeout_s = request.request_timeout_ms / 1000
        async with Client(endpoint, timeout=timeout_s) as client:
            nodes = [client.get_node(nid) for nid in node_ids]
            values = await client.read_values(nodes)

        return [
            AcquiredNodeState(
                source_id=request.source_id,
                node_key=item.key,
                value=str(value),
                observed_at=observed_at,
            )
            for item, value in zip(request.items, values, strict=True)
        ]

    async def subscribe(self, request: SourceSubscriptionRequest) -> None:
        if request.stop_requested is None:
            raise ValueError("Subscription request must provide a stop callback.")
        if request.state_received is None:
            raise ValueError("Subscription request must provide a state callback.")

        if not request.items:
            while not request.stop_requested():
                await asyncio.sleep(0.1)
            return

        endpoint = self._resolve_endpoint(request)
        if not endpoint:
            raise ValueError("Cannot resolve OPC UA endpoint.")

        node_ids = self._resolve_node_ids(request)
        if not node_ids:
            raise ValueError("Cannot resolve OPC UA node IDs.")

        async with Client(endpoint, timeout=10) as client:
            nodes = [client.get_node(node_id) for node_id in node_ids]
            handler = _OpcUaSubscriptionHandler(
                source_id=request.source_id,
                node_keys_by_node_id={
                    node_id: item.key
                    for item, node_id in zip(request.items, node_ids, strict=True)
                },
                state_received=request.state_received,
            )
            subscription = await client.create_subscription(100, handler)
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

    # ── Endpoint resolution ─────────────────────────────────────────

    @staticmethod
    def _resolve_endpoint(request: SourceAcquisitionRequest | SourceSubscriptionRequest) -> str:
        if request.resolved_endpoint:
            return request.resolved_endpoint
        if request.connection.endpoint:
            return request.connection.endpoint
        return ""

    # ── Node ID resolution ──────────────────────────────────────────

    @staticmethod
    def _resolve_node_ids(request: SourceAcquisitionRequest | SourceSubscriptionRequest) -> list[str]:
        if request.resolved_node_ids:
            return list(request.resolved_node_ids)

        ns_uri_raw = request.connection.params.get("namespace_uri")
        ns_uri = ns_uri_raw.strip() if isinstance(ns_uri_raw, str) and ns_uri_raw.strip() else ""

        node_ids: list[str] = []
        for item in request.items:
            if item.locator.startswith("ns=") or item.locator.startswith("nsu="):
                node_ids.append(item.locator)
            else:
                node_ids.append(f"nsu={ns_uri};s={item.locator}" if ns_uri else f"s={item.locator}")
        return node_ids

    # ── Helpers ─────────────────────────────────────────────────────

    @staticmethod
    def _normalize_subscription_handles(handles: Any) -> list[int]:
        if isinstance(handles, list):
            return [handle for handle in handles if isinstance(handle, int)]
        if isinstance(handles, int):
            return [handles]
        return []


# ═══════════════════════════════════════════════════════════════════════
# Subscription handler
# ═══════════════════════════════════════════════════════════════════════

class _OpcUaSubscriptionHandler:
    """Translate OPC UA data-change notifications into acquired node states."""

    def __init__(
        self,
        *,
        source_id: str,
        node_keys_by_node_id: dict[str, str],
        state_received: SubscriptionStateHandler,
    ) -> None:
        self._source_id = source_id
        self._node_keys_by_node_id = dict(node_keys_by_node_id)
        self._state_received = state_received

    async def datachange_notification(self, node: object, val: object, data: object) -> None:
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
        node_id = getattr(node, "nodeid", node)
        return str(node_id)

    @staticmethod
    def _resolve_observed_at(data: object) -> datetime:
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
