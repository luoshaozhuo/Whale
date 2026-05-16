from __future__ import annotations

import os

from whale.shared.source.models import SourceConnectionProfile
from whale.shared.source.opcua.backends.asyncua_backend import AsyncuaOpcUaClientBackend
from whale.shared.source.opcua.backends.base import OpcUaClientBackend
from whale.shared.source.opcua.backends.open62541_backend import Open62541OpcUaClientBackend


def normalize_client_backend_name(name: str) -> str:
    """Normalize one raw client-backend label to a supported canonical name."""

    normalized = name.strip().lower().replace("_", "").replace("-", "")
    if normalized in {"asyncua", "async"}:
        return "asyncua"
    if normalized in {"open62541", "open"}:
        return "open62541"
    raise ValueError(f"Unsupported OPC UA client backend: {name!r}")


def resolve_client_backend_name(connection: SourceConnectionProfile) -> str:
    """Resolve OPC UA client backend name from params, test env, prod env, then default."""

    params_backend = connection.params.get("client_backend")
    if isinstance(params_backend, str) and params_backend.strip():
        return normalize_client_backend_name(params_backend)

    source_sim_backend = os.environ.get("SOURCE_SIM_OPCUA_CLIENT_BACKEND")
    if source_sim_backend:
        return normalize_client_backend_name(source_sim_backend)

    whale_backend = os.environ.get("WHALE_OPCUA_CLIENT_BACKEND")
    if whale_backend:
        return normalize_client_backend_name(whale_backend)

    return "asyncua"


def build_opcua_client_backend(connection: SourceConnectionProfile) -> OpcUaClientBackend:
    """Build one concrete OPC UA client backend for the given connection."""

    backend_name = resolve_client_backend_name(connection)
    if backend_name == "asyncua":
        return AsyncuaOpcUaClientBackend(connection)
    if backend_name == "open62541":
        return Open62541OpcUaClientBackend(connection)
    raise AssertionError(f"Unhandled OPC UA client backend: {backend_name}")
