"""Connection data DTO for one source acquisition request."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class SourceConnectionData:
    """Connection parameters required to talk to one source endpoint."""

    endpoint: str
    security_policy: str | None
    security_mode: str | None
    update_interval_ms: int
