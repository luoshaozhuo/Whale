"""Tests for source_lab simulator factory."""

from __future__ import annotations

import pytest

from tools.source_lab.opcua.asyncua_source_simulator import (
    AsyncuaSourceSimulator,
)
from tools.source_lab.opcua.open62541_source_simulator import (
    Open62541SourceSimulator,
)
from tools.source_lab.factory import build_simulator
from tools.source_lab.model import SimulatedPoint, SimulatedSource, SourceConnection


def _build_source(protocol: str = "opcua") -> SimulatedSource:
    """Build minimal simulated source for factory tests."""
    return SimulatedSource(
        connection=SourceConnection(
            name="source_001",
            ied_name="IED001",
            ld_name="LD0",
            host="127.0.0.1",
            port=4840,
            transport="tcp",
            protocol=protocol,
            namespace_uri="urn:whale:test",
        ),
        points=(
            SimulatedPoint(
                ln_name="WPPD1",
                do_name="TotW",
                unit="kW",
                data_type="FLOAT64",
                initial_value=1.0,
            ),
        ),
    )


def test_build_simulator_uses_asyncua_backend_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    """Default OPC UA backend should remain asyncua."""
    monkeypatch.delenv("SOURCE_SIM_OPCUA_BACKEND", raising=False)

    simulator = build_simulator(_build_source())

    assert isinstance(simulator, AsyncuaSourceSimulator)


def test_build_simulator_uses_asyncua_backend_explicitly(monkeypatch: pytest.MonkeyPatch) -> None:
    """Explicit asyncua backend should build AsyncuaSourceSimulator."""
    monkeypatch.setenv("SOURCE_SIM_OPCUA_BACKEND", "asyncua")

    simulator = build_simulator(_build_source())

    assert isinstance(simulator, AsyncuaSourceSimulator)


def test_build_simulator_uses_open62541_backend(monkeypatch: pytest.MonkeyPatch) -> None:
    """Explicit open62541 backend should build Open62541SourceSimulator."""
    monkeypatch.setenv("SOURCE_SIM_OPCUA_BACKEND", "open62541")

    simulator = build_simulator(_build_source())

    assert isinstance(simulator, Open62541SourceSimulator)


def test_build_simulator_normalizes_backend_name(monkeypatch: pytest.MonkeyPatch) -> None:
    """Backend labels should allow simple spelling variants."""
    monkeypatch.setenv("SOURCE_SIM_OPCUA_BACKEND", "open_62541")

    simulator = build_simulator(_build_source())

    assert isinstance(simulator, Open62541SourceSimulator)


def test_build_simulator_rejects_unknown_backend(monkeypatch: pytest.MonkeyPatch) -> None:
    """Unknown OPC UA backend should fail fast."""
    monkeypatch.setenv("SOURCE_SIM_OPCUA_BACKEND", "unknown")

    with pytest.raises(ValueError, match="Unsupported OPC UA source simulator backend"):
        build_simulator(_build_source())


def test_build_simulator_rejects_unknown_protocol(monkeypatch: pytest.MonkeyPatch) -> None:
    """Unknown protocol should fail fast."""
    monkeypatch.delenv("SOURCE_SIM_OPCUA_BACKEND", raising=False)

    with pytest.raises(ValueError, match="Unsupported source simulator type"):
        build_simulator(_build_source(protocol="modbus"))