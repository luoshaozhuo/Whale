"""Source acquisition port registry for ingest."""

from __future__ import annotations

from typing import Protocol

from whale.ingest.ports.source.source_acquisition_port import SourceAcquisitionPort


class SourceAcquisitionPortRegistry(Protocol):
    """Resolve one acquisition port implementation for a protocol."""

    def get(self, protocol: str) -> SourceAcquisitionPort:
        """Return the acquisition port registered for the given protocol."""
