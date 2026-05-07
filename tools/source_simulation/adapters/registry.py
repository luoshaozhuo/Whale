"""Explicit simulator builder registry."""

from __future__ import annotations

from collections.abc import Callable

from tools.source_simulation.adapters.opcua.source_simulator import OpcUaSourceSimulator
from tools.source_simulation.domain import SimulatedSource
from tools.source_simulation.ports import SourceSimulator


SimulatorBuilder = Callable[[SimulatedSource], SourceSimulator]


def builders_by_type() -> dict[str, SimulatorBuilder]:
    """Return the known simulator builders keyed by normalized protocol name."""
    return {
        "opcua": OpcUaSourceSimulator,
    }


def _normalize_protocol(protocol: str) -> str:
    """Normalize protocol labels such as OPC_UA to the registry key."""
    return protocol.strip().lower().replace("_", "").replace("-", "")


def get_builder(protocol: str) -> SimulatorBuilder:
    """Resolve one simulator builder from the explicit registry."""
    try:
        return builders_by_type()[_normalize_protocol(protocol)]
    except KeyError as exc:
        raise ValueError(f"Unsupported source simulator type: {protocol}") from exc


def build_simulator(
    source: SimulatedSource,
) -> SourceSimulator:
    """Build one simulator directly from one source definition."""
    return get_builder(source.connection.protocol)(source)
