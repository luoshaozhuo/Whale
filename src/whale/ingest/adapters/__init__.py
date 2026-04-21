"""Adapters for the ingest module."""

from whale.ingest.adapters.config import (
    SourceConnectionConfigRepository,
    SourceScheduleConfigRepository,
)

__all__ = [
    "SourceConnectionConfigRepository",
    "SourceScheduleConfigRepository",
]
