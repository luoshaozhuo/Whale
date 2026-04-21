"""Adapters for the ingest module."""

from whale.ingest.adapters.config import (
    DbSourceConfigAdapter,
    DbSourceRuntimeConfigAdapter,
)

__all__ = ["DbSourceConfigAdapter", "DbSourceRuntimeConfigAdapter"]
