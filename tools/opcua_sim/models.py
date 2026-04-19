"""Lightweight data models for OPC UA simulator bootstrap."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class OpcUaServerConfig:
    """Describe how to bootstrap one simulator server from fixture files.

    Attributes:
        name: Logical server name taken from the connection config.
        endpoint: OPC UA endpoint used by the server runtime.
        security_policy: Security policy string from the YAML config.
        security_mode: Security mode string from the YAML config.
        update_interval_seconds: Period used to refresh simulated variable values.
    """

    name: str
    endpoint: str
    security_policy: str
    security_mode: str
    update_interval_seconds: float
