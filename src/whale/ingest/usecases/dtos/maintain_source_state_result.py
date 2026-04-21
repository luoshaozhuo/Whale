"""Result DTO for the maintain-source-state use case.

This result currently only exposes minimal execution statistics. Future
iterations may extend it with health information, timings, and failure details.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class MaintainSourceStateResult:
    """Minimal execution result for one source-state maintenance step."""

    source_id: str
    received_count: int
    updated_count: int
