"""Source execution-plan port for ingest."""

from __future__ import annotations

from typing import Protocol

from whale.ingest.usecases.dtos.source_execution_plan import SourceExecutionPlan


class SourceExecutionPlanPort(Protocol):
    """Load fully joined execution plans for enabled ingest sources."""

    def get_enabled_execution_plans(self) -> list[SourceExecutionPlan]:
        """Return enabled source execution plans."""
