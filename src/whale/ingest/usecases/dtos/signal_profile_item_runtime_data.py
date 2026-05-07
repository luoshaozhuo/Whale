"""Signal-profile item DTO used by source simulation runtime loading."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class SignalProfileItemRuntimeData:
    """Describe one signal item resolved directly from one shared signal profile."""

    signal_profile_id: int
    ln_name: str | None
    do_name: str
    relative_path: str
    data_type: str
    unit: str | None
