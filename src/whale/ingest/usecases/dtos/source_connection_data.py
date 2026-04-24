"""Connection data DTO for one source acquisition request."""

from __future__ import annotations

from dataclasses import dataclass, field

ConnectionParamValue = str | int | float | bool | None


@dataclass(slots=True)
class SourceConnectionData:
    """Connection parameters required to talk to one source endpoint."""

    endpoint: str | None = None
    host: str | None = None
    port: int | None = None
    username: str | None = None
    password: str | None = None
    params: dict[str, ConnectionParamValue] = field(default_factory=dict)
