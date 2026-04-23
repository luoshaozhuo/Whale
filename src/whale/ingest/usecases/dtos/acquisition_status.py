"""Acquisition-status values shared by the ingest refresh flow."""

from __future__ import annotations

from enum import StrEnum


class AcquisitionStatus(StrEnum):
    """Represent the business status of one refresh acquisition step."""

    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    EMPTY = "EMPTY"
    DISABLED = "DISABLED"
