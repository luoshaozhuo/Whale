"""Shared contract for source simulators used by the fleet."""

from __future__ import annotations

from typing import Protocol


class SourceSimulator(Protocol):
    """Lifecycle contract for one running simulated server."""

    @property
    def endpoint(self) -> str: ...

    @property
    def name(self) -> str: ...

    def start(self) -> "SourceSimulator": ...

    def stop(self) -> None: ...

    def discover_write_points(self) -> tuple[tuple[str, str], ...]: ...

    def writes(self, values_by_key: dict[str, str | int | float | bool]) -> None: ...
