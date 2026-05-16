from __future__ import annotations

import asyncio
from collections.abc import Sequence
from datetime import datetime, timezone
from typing import Any

from asyncua import Client, Node, ua  # type: ignore[import-untyped]
from asyncua.ua.ua_binary import struct_from_binary  # type: ignore[import-untyped]

from whale.shared.source.models import SourceConnectionProfile
from whale.shared.source.opcua.backends.base import (
    AsyncuaPreparedReadPlan,
    PreparedReadPlan,
    RawOpcUaReadResult,
)


def _raw_datetime(value: object) -> datetime | None:
    """Normalize asyncua timestamps to timezone-aware UTC datetimes."""

    if not isinstance(value, datetime):
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


class AsyncuaOpcUaClientBackend:
    """asyncua-based OPC UA client backend for raw polling."""

    def __init__(self, connection: SourceConnectionProfile) -> None:
        """Initialize one asyncua backend for raw polling operations."""

        self._connection = connection
        self._client: Client | None = None
        self._nsidx: int | None = None
        self._read_batch_cache: dict[tuple[str, ...], AsyncuaPreparedReadPlan] = {}

    async def connect(self) -> None:
        """Open asyncua client session and resolve namespace index."""

        client = Client(self._connection.endpoint, timeout=self._connection.timeout_seconds)
        await client.connect()
        self._client = client
        self._nsidx = await self._resolve_namespace_index(client)

    async def disconnect(self) -> None:
        """Close asyncua client session and drop prepared-read cache."""

        try:
            if self._client is not None:
                await self._client.disconnect()
        finally:
            self._client = None
            self._nsidx = None
            self._read_batch_cache.clear()

    @property
    def client(self) -> Client:
        """Expose the connected asyncua client for reader-side compatibility."""

        return self._client_or_raise()

    @property
    def namespace_index(self) -> int | None:
        """Return resolved namespace index, if configured."""

        return self._nsidx

    def prepare_read(self, addresses: Sequence[str]) -> AsyncuaPreparedReadPlan:
        """Prepare a reusable full-read plan without issuing network traffic."""

        normalized_paths = self._normalize_node_paths(addresses)
        return self._get_or_build_read_batch(normalized_paths)

    async def read_prepared_raw(
        self,
        plan: PreparedReadPlan,
    ) -> RawOpcUaReadResult:
        """Read prepared DataValues without constructing Batch or NodeValueChange."""
        if not isinstance(plan, AsyncuaPreparedReadPlan):
            raise TypeError("AsyncuaOpcUaClientBackend requires AsyncuaPreparedReadPlan")

        retry_count = 0
        max_retries = 1

        while retry_count <= max_retries:
            try:
                data_values, response_timestamp = await self._read_data_values(
                    plan.read_params,
                )
                return RawOpcUaReadResult(
                    ok=True,
                    data_values=data_values,
                    response_timestamp=response_timestamp,
                    retry_count=retry_count,
                )
            except (asyncio.TimeoutError, Exception) as ex:
                retry_count += 1
                if retry_count > max_retries:
                    return RawOpcUaReadResult(
                        ok=False,
                        data_values=(),
                        response_timestamp=None,
                        error_reason="timeout" if isinstance(ex, asyncio.TimeoutError) else "read_failed",
                        exception=str(ex),
                        retry_count=retry_count,
                    )
                await asyncio.sleep(0.05)

        return RawOpcUaReadResult(
            ok=False,
            data_values=(),
            response_timestamp=None,
            error_reason="read_failed",
            retry_count=max_retries + 1,
        )

    def _client_or_raise(self) -> Client:
        """Return connected asyncua client or raise one clear runtime error."""

        if self._client is None:
            raise RuntimeError("OPC UA client is not connected")
        return self._client

    def _get_or_build_read_batch(
        self,
        node_paths: Sequence[str],
    ) -> AsyncuaPreparedReadPlan:
        """Get cached node objects and ReadParameters for one stable path batch."""

        cache_key = tuple(node_paths)
        cached = self._read_batch_cache.get(cache_key)
        if cached is not None:
            return cached

        client = self._client_or_raise()
        nodes: list[Node] = []
        for path in node_paths:
            nodes.append(client.get_node(path))

        read_params = ua.ReadParameters()
        read_params.TimestampsToReturn = ua.TimestampsToReturn.Both

        for node in nodes:
            node_id = getattr(node, "nodeid", None)
            if node_id is None:
                continue
            read_value_id = ua.ReadValueId()
            read_value_id.NodeId = node_id
            read_value_id.AttributeId = ua.AttributeIds.Value
            read_params.NodesToRead.append(read_value_id)

        entry = AsyncuaPreparedReadPlan(
            node_paths=tuple(node_paths),
            nodes=tuple(nodes),
            read_params=read_params,
        )
        self._read_batch_cache[cache_key] = entry
        return entry

    def _normalize_node_paths(self, node_paths: Sequence[str]) -> tuple[str, ...]:
        """Normalize node paths by applying namespace index when needed."""

        return tuple(
            path if path.startswith(("ns=", "nsu=")) else self._with_namespace_index(path)
            for path in node_paths
        )

    def _with_namespace_index(self, node_path: str) -> str:
        """Add namespace index prefix to one node path when not already present."""

        if self._nsidx is None:
            raise RuntimeError("Namespace index not initialized")
        return f"ns={self._nsidx};{node_path}"

    async def _resolve_namespace_index(self, client: Client) -> int | None:
        """Resolve namespace index from connection namespace URI when configured."""

        namespace_uri = self._connection.namespace_uri or self._connection.params.get("namespace_uri")
        if not namespace_uri:
            return None
        return int(await client.get_namespace_index(namespace_uri))

    async def _read_data_values(
        self,
        read_params: ua.ReadParameters,
    ) -> tuple[Sequence[ua.DataValue], datetime | None]:
        """Read Value DataValues with one response timestamp near server handling."""

        client = self._client_or_raise()
        request = ua.ReadRequest()
        request.Parameters = read_params
        data = await asyncio.wait_for(
            client.uaclient.protocol.send_request(request),
            timeout=self._connection.timeout_seconds,
        )
        response = struct_from_binary(ua.ReadResponse, data)
        response.ResponseHeader.ServiceResult.check()
        return (
            response.Results,
            _raw_datetime(response.ResponseHeader.Timestamp),
        )
