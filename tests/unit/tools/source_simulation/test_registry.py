"""Unit tests for the explicit source-simulation builder registry."""

from __future__ import annotations

import pytest

from tools.source_simulation.adapters.opcua import OpcUaSourceSimulator
from tools.source_simulation.adapters.registry import build_simulator
from tools.source_simulation.domain import (
    SimulatedSource,
    SourceConnection,
)


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
            namespace_uri="urn:test:registry",
        ),
        points=(),
    )
    simulator = build_simulator(source)

    assert simulator.name == "WTG_01"
    assert simulator.endpoint == "opc.tcp://127.0.0.1:4840"
    assert isinstance(simulator, OpcUaSourceSimulator)


@pytest.mark.unit
def test_build_simulator_rejects_unknown_protocol() -> None:
    """Raise a clear error for an unsupported simulator type."""
    source = SimulatedSource(
        connection=SourceConnection(
            name="S1",
            ied_name="IED1",
            ld_name="LD0",
            host="127.0.0.1",
            port=502,
            transport="tcp",
            protocol="modbus",
        ),
        points=(),
    )

    with pytest.raises(ValueError, match="Unsupported source simulator type"):
        build_simulator(source)
