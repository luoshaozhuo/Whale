"""Mock OPC UA collector for scenario1."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from whale.scenario1.models import RawBatch
from whale.shared.utils.time import ensure_utc, parse_iso_datetime


class CollectorError(ValueError):
    """Raised when incoming mock OPC UA data is invalid."""


def build_raw_batch(payload: dict[str, Any]) -> RawBatch:
    """Build the ODS raw-batch model from a stable mock payload.

    Args:
        payload: Mock OPC UA batch payload containing batch identity, receive
            time, turbine id, event time, and measurement list.

    Returns:
        A `RawBatch` ready to be persisted into ODS.

    Raises:
        CollectorError: If required fields are missing or timestamps are invalid.
    """
    required = {"batch_id", "recv_time", "turbine_id", "event_time", "measurements"}
    missing = sorted(field for field in required if field not in payload)
    if missing:
        raise CollectorError(f"Raw payload missing required fields: {', '.join(missing)}")

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
    raise CollectorError(f"Unsupported datetime value: {value!r}")
