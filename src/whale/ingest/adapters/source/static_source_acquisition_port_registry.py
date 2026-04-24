"""Static acquisition-port registry for ingest composition."""

from __future__ import annotations

from collections.abc import Mapping

from whale.ingest.ports.source.source_acquisition_port import SourceAcquisitionPort


class StaticSourceAcquisitionPortRegistry:
    """Resolve acquisition ports from one static protocol mapping."""

    def __init__(self, ports_by_protocol: Mapping[str, SourceAcquisitionPort]) -> None:
        """Store the configured acquisition-port mapping."""
        self._ports_by_protocol = dict(ports_by_protocol)

    def get(self, protocol: str) -> SourceAcquisitionPort:
        """Return the acquisition port for one protocol or raise when unsupported."""
        try:
            return self._ports_by_protocol[protocol]
        except KeyError as exc:
            raise ValueError(f"Unsupported acquisition protocol: {protocol}") from exc
