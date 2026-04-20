"""Helpers for building `RawBatch` models from stable payload objects."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from whale.models import RawBatch
from whale.shared.utils.time import ensure_utc, parse_iso_datetime


class RawBatchBuildError(ValueError):
    """Raised when an incoming raw payload cannot be converted into `RawBatch`."""


def build_raw_batch(payload: dict[str, Any]) -> RawBatch:
    """Build the ODS raw-batch model from a stable payload.

    Args:
        payload: Raw payload containing batch identity, receive time, turbine id,
            event time, and measurement list.

    Returns:
        A `RawBatch` ready to be persisted into ODS.

    Raises:
        RawBatchBuildError: If required fields are missing or timestamps are invalid.
    """
    required = {"batch_id", "recv_time", "turbine_id", "event_time", "measurements"}
    missing = sorted(field for field in required if field not in payload)
    if missing:
        raise RawBatchBuildError(f"Raw payload missing required fields: {', '.join(missing)}")

    recv_time = _parse_time(payload["recv_time"])
    raw_payload = {
        "event_time": payload["event_time"],
        "measurements": payload["measurements"],
    }
    return RawBatch(
        batch_id=str(payload["batch_id"]),
        recv_time=recv_time,
        turbine_id=str(payload["turbine_id"]),
        raw_payload=raw_payload,
    )


def _parse_time(value: str | datetime) -> datetime:
    """Parse datetime input into UTC."""
    if isinstance(value, datetime):
        return ensure_utc(value)
    if isinstance(value, str):
        return parse_iso_datetime(value)
    raise RawBatchBuildError(f"Unsupported datetime value: {value!r}")
