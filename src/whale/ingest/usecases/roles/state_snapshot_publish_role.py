"""State snapshot publish role for ingest."""

from __future__ import annotations

from datetime import UTC, datetime

from whale.ingest.ports.message import MessagePublisherPort
from whale.ingest.usecases.dtos.message_publish_result import MessagePublishResult
from whale.ingest.usecases.dtos.state_snapshot_message import StateSnapshotMessage


class StateSnapshotPublishRole:
    """Publish one assembled snapshot message through the configured backend."""

    def __init__(self, publisher: MessagePublisherPort) -> None:
        """Store the publisher used during publish execution."""
        self._publisher = publisher

    def publish(self, message: StateSnapshotMessage) -> MessagePublishResult:
        """Publish one snapshot message through the configured publisher."""
        try:
            return self._publisher.publish_snapshot(message)
        except Exception as exc:
            return MessagePublishResult(
                pipeline_name=self._publisher.__class__.__name__,
                success=False,
                message_id=message.message_id,
                message_count=0,
                published_at=datetime.now(tz=UTC),
                error_message=str(exc),
            )
