"""Acquisition mode enumeration for ingest runtime."""

from __future__ import annotations

from enum import StrEnum


class AcquisitionMode(StrEnum):
    """Supported acquisition modes."""

    ONCE = "ONCE"
    POLLING = "POLLING"
    SUBSCRIPTION = "SUBSCRIPTION"
