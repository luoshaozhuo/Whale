"""Acquisition-item DTO for one source request."""

from __future__ import annotations

from dataclasses import dataclass, field

AcquisitionParamValue = str | int | float | bool | None


@dataclass(slots=True)
class AcquisitionItemData:
    """Describe one source item that should be acquired."""

    key: str
    locator: str
    locator_type: str | None = None
    display_name: str | None = None
    params: dict[str, AcquisitionParamValue] = field(default_factory=dict)
