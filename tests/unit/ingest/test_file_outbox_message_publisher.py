"""Unit tests for the file outbox snapshot publisher."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from whale.ingest.adapters.message.file_outbox_message_publisher import (
    FileOutboxMessagePublisher,
)
from whale.ingest.usecases.dtos.state_snapshot_message import StateSnapshotMessage


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


def test_publish_snapshot_writes_one_jsonl_record(tmp_path: Path) -> None:
    """Write one snapshot message into the expected date-partitioned JSONL file."""
    publisher = FileOutboxMessagePublisher(tmp_path)

    result = publisher.publish_snapshot(_build_message())

    output_path = (
        tmp_path / "ingest" / "state_snapshot" / "v1" / "2026-04-25" / "state-snapshot-10.jsonl"
    )
    rows = output_path.read_text(encoding="utf-8").splitlines()
    assert result.pipeline_name == "file_outbox"
    assert result.success is True
    assert len(rows) == 1
    assert json.loads(rows[0])["message_id"] == "msg-001"
