"""Configuration adapters for ingest."""

from whale.ingest.adapters.config.db_source_config_adapter import DbSourceConfigAdapter
from whale.ingest.adapters.config.db_source_runtime_config_adapter import (
    DbSourceRuntimeConfigAdapter,
)

__all__ = ["DbSourceConfigAdapter", "DbSourceRuntimeConfigAdapter"]
