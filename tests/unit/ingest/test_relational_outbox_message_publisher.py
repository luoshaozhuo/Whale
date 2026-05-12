"""Unit tests for the relational outbox snapshot publisher."""

from __future__ import annotations

from datetime import UTC, datetime

from whale.ingest.adapters.message.relational_outbox_message_publisher import (
    RelationalOutboxMessagePublisher,
)
from whale.ingest.ports.message.message_publisher_port import StateSnapshotMessage


def _build_message() -> StateSnapshotMessage:
    """Build one minimal snapshot message for publisher tests."""
    snapshot_at = datetime(2026, 4, 25, 10, 30, tzinfo=UTC)
    return StateSnapshotMessage(
        message_id="msg-001",
        schema_version="v1",
        message_type="STATE_SNAPSHOT",
        source_module="ingest",
        snapshot_id="snapshot-001",
        snapshot_at=snapshot_at,
        item_count=0,
        items=[],
        trace_id="trace-001",
    )


def test_publish_snapshot_returns_success_for_noop_outbox() -> None:
    """Return a success result even though the outbox table was removed."""
    publisher = RelationalOutboxMessagePublisher()

    result = publisher.publish_snapshot(_build_message())

    assert result.pipeline_name == "relational_outbox"
    assert result.success is True
    assert result.message_id == "msg-001"
    assert result.message_count == 1
