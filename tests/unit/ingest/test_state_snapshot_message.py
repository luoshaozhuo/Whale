"""Unit tests for state snapshot message serialization."""

from __future__ import annotations

from datetime import UTC, datetime

from whale.ingest.usecases.dtos.state_snapshot_message import (
    StateSnapshotItem,
    StateSnapshotMessage,
)


def test_state_snapshot_message_serialization_is_stable() -> None:
    """Serialize one snapshot message with stable field names and values."""
    observed_at = datetime(2026, 4, 25, 10, 0, tzinfo=UTC)
    message = StateSnapshotMessage(
        message_id="msg-001",
        schema_version="v1",
        message_type="STATE_SNAPSHOT",
        source_module="ingest",
        snapshot_id="snapshot-001",
        snapshot_at=observed_at,
        item_count=1,
        items=[
            StateSnapshotItem(
                station_id="station-001",
                device_id=None,
                device_code="WTG_01",
                model_id="model_1",
                variable_key="TotW",
                value="1200.0",
                value_type=None,
                quality_code=None,
                source_observed_at=observed_at,
                received_at=observed_at,
                updated_at=observed_at,
            )
        ],
        trace_id="trace-001",
        attributes={"env": "test"},
    )

    payload = message.to_dict()
    serialized = message.to_json()

    assert list(payload) == [
        "message_id",
        "schema_version",
        "message_type",
        "source_module",
        "snapshot_id",
        "snapshot_at",
        "item_count",
        "items",
        "trace_id",
        "attributes",
    ]
    assert payload["message_type"] == "STATE_SNAPSHOT"
    assert payload["item_count"] == 1
    items = payload["items"]
    assert isinstance(items, list)
    first_item = items[0]
    assert isinstance(first_item, dict)
    assert first_item["device_code"] == "WTG_01"
    assert '"message_id":"msg-001"' in serialized
    assert '"snapshot_id":"snapshot-001"' in serialized
