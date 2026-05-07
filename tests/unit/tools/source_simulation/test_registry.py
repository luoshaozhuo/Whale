"""Unit tests for the explicit source-simulation builder registry."""

from __future__ import annotations

import pytest

from tools.source_simulation.adapters.opcua import OpcUaSourceSimulator
from tools.source_simulation.adapters.registry import build_simulator, get_builder
from tools.source_simulation.domain import (
    SimulatedSource,
    SourceConnection,
)


@pytest.mark.unit
def test_get_builder_returns_registered_opcua_builder() -> None:
    """Resolve the explicit OPC UA simulator builder from the registry."""
    builder = get_builder("opcua")

    assert builder is OpcUaSourceSimulator


@pytest.mark.unit
def test_get_builder_rejects_unknown_simulator_type() -> None:
    """Raise a clear error for an unsupported simulator type."""
    with pytest.raises(ValueError, match="Unsupported source simulator type"):
        get_builder("modbus")


@pytest.mark.unit
def test_build_simulator_uses_source_simulator_type() -> None:
    """Build a concrete simulator directly from one source definition."""
    source = SimulatedSource(
        connection=SourceConnection(
            name="WTG_01",
            ied_name="WTG_01",
            ld_name="LD0",
            host="127.0.0.1",
            port=4840,
            transport="tcp",
            protocol="opcua",
            params={"namespace_uri": "urn:test:registry"},
        ),
        points=(),
    )
    simulator = build_simulator(source)

    assert simulator.name == "WTG_01"
    assert simulator.endpoint == "opc.tcp://127.0.0.1:4840"
