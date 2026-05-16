"""Internal typing contracts for source_lab.

This module is a lightweight tool-side typing helper. It is not a
production ports/adapters architecture boundary.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol

from tools.source_lab.model import SourceNodeInfo, SourceReadPoint


class SourceSimulator(Protocol):
    """Lifecycle contract for one running simulated server."""

    @property
    def endpoint(self) -> str: ...

    @property
    def name(self) -> str: ...

    def start(self) -> "SourceSimulator": ...

    def stop(self) -> None: ...

    def __enter__(self) -> "SourceSimulator": ...

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None: ...

    def writes(self, values_by_key: dict[str, str | int | float | bool]) -> None: ...


class SourceReader(Protocol):
    """Async read contract for inspecting one running simulated source."""

    async def __aenter__(self) -> "SourceReader": ...

    async def __aexit__(self, exc_type: object, exc: object, tb: object) -> None: ...

    async def read(
        self,
        node_paths: Sequence[str],
        *,
        fast_mode: bool = True,
    ) -> tuple[SourceReadPoint, ...]: ...

    async def list_nodes(self) -> tuple[SourceNodeInfo, ...]: ...
