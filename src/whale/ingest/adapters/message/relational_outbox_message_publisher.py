"""Relational outbox publisher for ingest state snapshot messages.

Deprecated: StateSnapshotOutbox has been removed. This publisher is a no-op.
"""

from __future__ import annotations

from datetime import UTC, datetime

from whale.ingest.ports.message import MessagePublisherPort
from whale.ingest.ports.message.message_publisher_port import (
    MessagePublishResult,
    StateSnapshotMessage,
)


class RelationalOutboxMessagePublisher(MessagePublisherPort):
    """No-op outbox publisher (table removed in schema rewrite)."""

    def publish_snapshot(self, message: StateSnapshotMessage) -> MessagePublishResult:
        return MessagePublishResult(
            pipeline_name="relational_outbox",
            success=True,
            message_id=message.message_id,
            message_count=1,
            published_at=datetime.now(tz=UTC),
        )
