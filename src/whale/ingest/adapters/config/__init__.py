"""Configuration adapters for ingest."""

from whale.ingest.adapters.config.source_connection_config_repository import (
    SourceConnectionConfigRepository,
)
from whale.ingest.adapters.config.source_schedule_config_repository import (
    SourceScheduleConfigRepository,
)

__all__ = [
    "SourceConnectionConfigRepository",
    "SourceScheduleConfigRepository",
]
