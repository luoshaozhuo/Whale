"""Shared source-building helpers for OPC UA load tests.

This module re-exports the formal API from tools.source_lab.sources
to maintain backward compatibility for tests.
"""

from __future__ import annotations

# Re-export all public APIs from formal sources module
from tools.source_lab.sources import (
    PortAllocator,
    assign_dynamic_port,
    build_multi_sources,
    build_opcua_endpoint,
    build_opcua_source_from_repository,
    choose_available_port,
)

__all__ = [
    "PortAllocator",
    "assign_dynamic_port",
    "build_multi_sources",
    "build_opcua_endpoint",
    "build_opcua_source_from_repository",
    "choose_available_port",
]
