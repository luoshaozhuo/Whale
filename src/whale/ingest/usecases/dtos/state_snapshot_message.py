"""State snapshot message DTOs for downstream publishing."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime


@dataclass(slots=True)
class StateSnapshotItem:
    """Represent one variable row inside a published state snapshot."""

    station_id: str | None
    device_id: str | None
    device_code: str
    model_id: str
    variable_key: str
    value: str | None
    value_type: str | None
    quality_code: str | None
    source_observed_at: datetime | None
    received_at: datetime | None
    updated_at: datetime | None

    def to_dict(self) -> dict[str, object | None]:
        """Serialize one snapshot item into a JSON-friendly mapping."""
        return {
            "station_id": self.station_id,
            "device_id": self.device_id,
            "device_code": self.device_code,
            "model_id": self.model_id,
            "variable_key": self.variable_key,
            "value": self.value,
            "value_type": self.value_type,
            "quality_code": self.quality_code,
            "source_observed_at": _serialize_datetime(self.source_observed_at),
            "received_at": _serialize_datetime(self.received_at),
            "updated_at": _serialize_datetime(self.updated_at),
        }


@dataclass(slots=True)
class StateSnapshotMessage:
    """Represent one full snapshot message emitted by ingest."""

    message_id: str
    schema_version: str
    message_type: str
    source_module: str
    snapshot_id: str
    snapshot_at: datetime
    item_count: int
    items: list[StateSnapshotItem]
    trace_id: str | None = None
    attributes: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict[str, object]:
        """Serialize the full snapshot message into a JSON-friendly mapping."""
        return {
            "message_id": self.message_id,
            "schema_version": self.schema_version,
            "message_type": self.message_type,
            "source_module": self.source_module,
            "snapshot_id": self.snapshot_id,
            "snapshot_at": _serialize_datetime(self.snapshot_at),
            "item_count": self.item_count,
            "items": [item.to_dict() for item in self.items],
            "trace_id": self.trace_id,
            "attributes": dict(self.attributes),
        }

    def to_json(self) -> str:
        """Serialize the full snapshot message into one stable JSON string."""
        return json.dumps(
            self.to_dict(),
            ensure_ascii=False,
            separators=(",", ":"),
        )


def _serialize_datetime(value: datetime | None) -> str | None:
    """Serialize one optional datetime as ISO text."""
    if value is None:
        return None
    return value.isoformat()
