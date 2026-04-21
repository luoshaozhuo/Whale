"""Command DTO for the maintain-source-state use case.

This command is intentionally small for the first iteration. Future versions
may extend it with scheduling, filtering, and source-selection options.
"""

from __future__ import annotations

from dataclasses import dataclass

from whale.ingest.usecases.dtos.source_execution_plan import SourceExecutionPlan


@dataclass(slots=True)
class MaintainSourceStateCommand:
    """Input command for one source-state maintenance step."""

    execution_plan: SourceExecutionPlan
