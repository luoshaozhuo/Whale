"""Acquisition-item DTO for one source request."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class AcquisitionItemData:
    """Describe one source item that should be acquired."""

    key: str
    locator: str
