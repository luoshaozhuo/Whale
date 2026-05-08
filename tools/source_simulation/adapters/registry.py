"""Minimal source-simulation adapter factory functions."""

from __future__ import annotations

from tools.source_simulation.adapters.opcua.source_reader import OpcUaSourceReader
from tools.source_simulation.adapters.opcua.source_simulator import OpcUaSourceSimulator
from tools.source_simulation.domain import SimulatedSource, SourceConnection
from tools.source_simulation.ports import SourceReader, SourceSimulator

def _normalize_protocol(protocol: str) -> str:
    """Normalize protocol labels such as OPC_UA to a stable key."""
    return protocol.strip().lower().replace("_", "").replace("-", "")


def build_simulator(
    source: SimulatedSource,
) -> SourceSimulator:
    """Build one simulator directly from one source definition."""
    if _normalize_protocol(source.connection.protocol) == "opcua":
        return OpcUaSourceSimulator(source)
    raise ValueError(f"Unsupported source simulator type: {source.connection.protocol}")


def build_source_reader(connection: SourceConnection) -> SourceReader:
    """Build one source reader directly from one source connection."""
    if _normalize_protocol(connection.protocol) == "opcua":
        return OpcUaSourceReader(connection)
    raise ValueError(f"Unsupported source reader type: {connection.protocol}")
