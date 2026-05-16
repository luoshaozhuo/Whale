"""Unit tests for OPC UA client backend factory resolution."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass

import pytest

from whale.shared.source.models import SourceConnectionProfile
from whale.shared.source.opcua.backends import (
    AsyncuaOpcUaClientBackend,
    Open62541OpcUaClientBackend,
)
from whale.shared.source.opcua.backends.factory import (
    build_opcua_client_backend,
    normalize_client_backend_name,
    resolve_client_backend_name,
)
from whale.shared.source.opcua.reader import OpcUaSourceReader


@dataclass(frozen=True, slots=True)
class _FakePreparedReadPlan:
    """Minimal prepared-read plan used for reader guard-rail tests."""

    node_paths: tuple[str, ...]


def _connection(
    *,
    params: dict[str, str | int | float | bool | None] | None = None,
) -> SourceConnectionProfile:
    """Build one minimal OPC UA connection profile for backend-factory tests."""

    return SourceConnectionProfile(
        endpoint="opc.tcp://127.0.0.1:4840",
        namespace_uri="urn:test:reader",
        params=params or {},
    )


@pytest.mark.unit
def test_normalize_client_backend_name_accepts_asyncua_variants() -> None:
    """Normalization should keep supported asyncua labels on one canonical name."""

    assert normalize_client_backend_name("asyncua") == "asyncua"
    assert normalize_client_backend_name("async") == "asyncua"
    assert normalize_client_backend_name("async_ua") == "asyncua"
    assert normalize_client_backend_name("async-ua") == "asyncua"


@pytest.mark.unit
def test_normalize_client_backend_name_accepts_open62541_variants() -> None:
    """Normalization should keep supported open62541 labels on one canonical name."""

    assert normalize_client_backend_name("open62541") == "open62541"
    assert normalize_client_backend_name("open") == "open62541"
    assert normalize_client_backend_name("open_62541") == "open62541"
    assert normalize_client_backend_name("open-62541") == "open62541"


@pytest.mark.unit
def test_normalize_client_backend_name_rejects_unknown_values() -> None:
    """Unknown backend names should fail fast with the original label in the error."""

    with pytest.raises(ValueError, match="unknown"):
        normalize_client_backend_name("unknown")


@pytest.mark.unit
def test_backend_factory_defaults_to_asyncua(monkeypatch: pytest.MonkeyPatch) -> None:
    """Default client backend should remain asyncua."""

    monkeypatch.delenv("SOURCE_SIM_OPCUA_CLIENT_BACKEND", raising=False)
    monkeypatch.delenv("WHALE_OPCUA_CLIENT_BACKEND", raising=False)

    backend = build_opcua_client_backend(_connection())

    assert isinstance(backend, AsyncuaOpcUaClientBackend)
    assert resolve_client_backend_name(_connection()) == "asyncua"


@pytest.mark.unit
def test_backend_factory_uses_source_sim_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Test-scoped environment variable should control client backend selection."""

    monkeypatch.setenv("SOURCE_SIM_OPCUA_CLIENT_BACKEND", "async-ua")
    monkeypatch.delenv("WHALE_OPCUA_CLIENT_BACKEND", raising=False)

    backend = build_opcua_client_backend(_connection())

    assert isinstance(backend, AsyncuaOpcUaClientBackend)


@pytest.mark.unit
def test_backend_factory_uses_open62541_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Explicit open62541 client backend should build placeholder backend."""

    monkeypatch.setenv("SOURCE_SIM_OPCUA_CLIENT_BACKEND", "open_62541")
    monkeypatch.delenv("WHALE_OPCUA_CLIENT_BACKEND", raising=False)

    backend = build_opcua_client_backend(_connection())

    assert isinstance(backend, Open62541OpcUaClientBackend)
    assert resolve_client_backend_name(_connection()) == "open62541"


@pytest.mark.unit
def test_backend_factory_uses_whale_env_when_test_env_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Production environment variable should be used when test env is unset."""

    monkeypatch.delenv("SOURCE_SIM_OPCUA_CLIENT_BACKEND", raising=False)
    monkeypatch.setenv("WHALE_OPCUA_CLIENT_BACKEND", "asyncua")

    backend = build_opcua_client_backend(_connection())

    assert isinstance(backend, AsyncuaOpcUaClientBackend)


@pytest.mark.unit
def test_backend_factory_prefers_source_sim_env_over_whale_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Test environment variable should override the production environment variable."""

    monkeypatch.setenv("SOURCE_SIM_OPCUA_CLIENT_BACKEND", "asyncua")
    monkeypatch.setenv("WHALE_OPCUA_CLIENT_BACKEND", "open62541")

    backend = build_opcua_client_backend(_connection())

    assert isinstance(backend, AsyncuaOpcUaClientBackend)
    assert resolve_client_backend_name(_connection()) == "asyncua"


@pytest.mark.unit
def test_backend_factory_prefers_connection_params(monkeypatch: pytest.MonkeyPatch) -> None:
    """Connection params should override environment-level backend selection."""

    monkeypatch.setenv("SOURCE_SIM_OPCUA_CLIENT_BACKEND", "open62541")
    monkeypatch.setenv("WHALE_OPCUA_CLIENT_BACKEND", "open62541")

    backend = build_opcua_client_backend(_connection(params={"client_backend": "async_ua"}))

    assert isinstance(backend, AsyncuaOpcUaClientBackend)
    assert (
        resolve_client_backend_name(_connection(params={"client_backend": "async_ua"}))
        == "asyncua"
    )


@pytest.mark.unit
def test_backend_factory_rejects_unknown_backend(monkeypatch: pytest.MonkeyPatch) -> None:
    """Unknown client backend labels should fail fast with one clear error."""

    monkeypatch.setenv("SOURCE_SIM_OPCUA_CLIENT_BACKEND", "unknown")
    monkeypatch.delenv("WHALE_OPCUA_CLIENT_BACKEND", raising=False)

    with pytest.raises(ValueError, match="Unsupported OPC UA client backend"):
        build_opcua_client_backend(_connection())


@pytest.mark.unit
def test_reader_full_read_requires_asyncua_backend(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Full batch conversion should stay explicitly asyncua-only for now."""

    monkeypatch.setenv("SOURCE_SIM_OPCUA_CLIENT_BACKEND", "open62541")
    monkeypatch.delenv("WHALE_OPCUA_CLIENT_BACKEND", raising=False)

    reader = OpcUaSourceReader(_connection())

    with pytest.raises(NotImplementedError, match="full Batch read requires asyncua backend"):
        asyncio.run(
            reader.read_prepared(
                _FakePreparedReadPlan(node_paths=("ns=2;s=IED001.LD0.WPPD1.TotW",)),
                mode="full",
            )
        )


@pytest.mark.unit
def test_reader_value_only_read_requires_asyncua_backend(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Value-only reads should stay explicitly asyncua-only for now."""

    monkeypatch.setenv("SOURCE_SIM_OPCUA_CLIENT_BACKEND", "open62541")
    monkeypatch.delenv("WHALE_OPCUA_CLIENT_BACKEND", raising=False)

    reader = OpcUaSourceReader(_connection())

    with pytest.raises(NotImplementedError, match="value_only Batch read requires backend values"):
        asyncio.run(
            reader.read_prepared(
                _FakePreparedReadPlan(node_paths=("ns=2;s=IED001.LD0.WPPD1.TotW",)),
                mode="value_only",
            )
        )
