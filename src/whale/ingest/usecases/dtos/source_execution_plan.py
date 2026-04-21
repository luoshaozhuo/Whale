"""Execution plan DTO for one ingest source."""

from __future__ import annotations

from dataclasses import dataclass

from whale.ingest.usecases.dtos.source_connection_spec import SourceConnectionSpec
from whale.ingest.usecases.dtos.source_schedule_spec import SourceScheduleSpec


@dataclass(slots=True)
class SourceExecutionPlan:
    """Fully joined execution plan for one scheduler-dispatched source."""

    schedule: SourceScheduleSpec
    connection: SourceConnectionSpec
