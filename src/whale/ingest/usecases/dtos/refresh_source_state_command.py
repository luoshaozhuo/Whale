"""Command DTO for the refresh-source-state use case."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class RefreshSourceStateCommand:
    """Input command for one runtime-config-driven refresh step."""

    runtime_config_id: int
