"""File outbox publisher for ingest state snapshot messages."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from whale.ingest.ports.message import MessagePublisherPort
from whale.ingest.usecases.dtos.message_publish_result import MessagePublishResult
from whale.ingest.usecases.dtos.state_snapshot_message import StateSnapshotMessage


class FileOutboxMessagePublisher(MessagePublisherPort):
    """Append snapshot messages into date-partitioned JSONL outbox files."""

    def __init__(self, output_root: Path) -> None:
        """Store the outbox root path used for emitted snapshot messages."""
        self._output_root = output_root

    def publish_snapshot(self, message: StateSnapshotMessage) -> MessagePublishResult:
        """Append one snapshot message into the file outbox."""
        output_path = self._resolve_output_path(message.snapshot_at)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with output_path.open("a", encoding="utf-8", newline="\n") as output_file:
            output_file.write(message.to_json())
            output_file.write("\n")
        return MessagePublishResult(
            pipeline_name="file_outbox",
            success=True,
            message_id=message.message_id,
            message_count=1,
            published_at=datetime.now(tz=UTC),
        )

    def _resolve_output_path(self, snapshot_at: datetime) -> Path:
        """Resolve one outbox path for the given snapshot timestamp."""
        date_part = snapshot_at.strftime("%Y-%m-%d")
        hour_part = snapshot_at.strftime("%H")
        return (
            self._output_root
            / "ingest"
            / "state_snapshot"
            / "v1"
            / date_part
            / f"state-snapshot-{hour_part}.jsonl"
        )
