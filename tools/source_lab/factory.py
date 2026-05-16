"""Factory helpers for source_lab simulators and readers."""

from __future__ import annotations

import os
from collections.abc import Sequence
from typing import TypeAlias

from whale.shared.source.models import SourceConnectionProfile
from whale.shared.source.opcua.reader import OpcUaSourceReader
from tools.source_lab.opcua.address_space import build_endpoint
from tools.source_lab.opcua.asyncua_source_simulator import (
    AsyncuaSourceSimulator,
)
from tools.source_lab.opcua.open62541_source_simulator import (
    Open62541SourceSimulator,
)
from tools.source_lab.model import SourceNodeInfo, SourceReadPoint
from tools.source_lab.model import SimulatedSource
from tools.source_lab.contracts import SourceReader, SourceSimulator

SimulatorFactory: TypeAlias = type[AsyncuaSourceSimulator] | type[Open62541SourceSimulator]

_OPCUA_BACKENDS: dict[str, SimulatorFactory] = {
    "asyncua": AsyncuaSourceSimulator,
    "open62541": Open62541SourceSimulator,
}


def _normalize_key(value: str) -> str:
    """Normalize protocol or backend labels to stable key."""
    return value.strip().lower().replace("_", "").replace("-", "")


def _resolve_opcua_backend() -> str:
    """Resolve OPC UA simulator backend from environment.

    Returns:
        Normalized backend key.

    Raises:
        ValueError: If backend is unsupported.
    """
    backend = _normalize_key(os.environ.get("SOURCE_SIM_OPCUA_BACKEND", "asyncua"))

    if backend not in _OPCUA_BACKENDS:
        supported = ", ".join(sorted(_OPCUA_BACKENDS))
        raise ValueError(
            f"Unsupported OPC UA source simulator backend: {backend}. "
            f"Supported backends: {supported}"
        )

    return backend


def build_simulator(source: SimulatedSource) -> SourceSimulator:
    """Build one simulator directly from one source definition.

    Args:
        source: Simulated source definition.

    Returns:
        Source simulator instance.

    Raises:
        ValueError: If protocol or backend is unsupported.
    """
    protocol = _normalize_key(source.connection.protocol)

    if protocol == "opcua":
        backend = _resolve_opcua_backend()
        return _OPCUA_BACKENDS[backend](source)

    raise ValueError(f"Unsupported source simulator type: {source.connection.protocol}")


class _SourceLabOpcUaReaderAdapter:
    """Adapt the shared OPC UA reader to the source_lab reader contract."""

    def __init__(self, connection: SourceConnectionProfile) -> None:
        self._reader = OpcUaSourceReader(connection)

    async def __aenter__(self) -> "_SourceLabOpcUaReaderAdapter":
        await self._reader.__aenter__()
        return self

    async def __aexit__(self, exc_type: object, exc: object, tb: object) -> None:
        await self._reader.__aexit__(exc_type, exc, tb)

    async def read(
        self,
        node_paths: Sequence[str],
        *,
        fast_mode: bool = True,
    ) -> tuple[SourceReadPoint, ...]:
        batch = await self._reader.read(
            node_paths,
            mode="value_only" if fast_mode else "full",
        )
        return tuple(
            SourceReadPoint(
                path=change.node_key,
                value=change.value,
                status=change.quality,
                source_timestamp=change.source_timestamp,
                server_timestamp=change.server_timestamp,
            )
            for change in batch.changes
        )

    async def list_nodes(self) -> tuple[SourceNodeInfo, ...]:
        nodes = await self._reader.list_nodes()
        return tuple(
            SourceNodeInfo(
                node_path=node.node_path,
                data_type=node.data_type,
                ld_name=node.ld_name,
                ln_name=node.ln_name,
                do_name=node.do_name,
            )
            for node in nodes
        )


def _resolve_timeout_seconds(source_timeouts: object) -> float:
    for attribute in (
        "read_timeout_seconds",
        "request_timeout_seconds",
        "connect_timeout_seconds",
    ):
        value = getattr(source_timeouts, attribute, None)
        if value is not None and value > 0:
            return float(value)
    return 4.0


def build_source_reader(source_connection: object) -> SourceReader:
    """Build a source_lab-compatible OPC UA reader for one source connection."""

    protocol = _normalize_key(getattr(source_connection, "protocol"))
    if protocol != "opcua":
        raise ValueError(f"Unsupported source reader type: {getattr(source_connection, 'protocol')}")

    profile = SourceConnectionProfile(
        endpoint=build_endpoint(source_connection),
        namespace_uri=getattr(source_connection, "namespace_uri", None),
        timeout_seconds=_resolve_timeout_seconds(getattr(source_connection, "timeouts", None)),
        params=dict(getattr(source_connection, "params", {})),
    )
    return _SourceLabOpcUaReaderAdapter(profile)
