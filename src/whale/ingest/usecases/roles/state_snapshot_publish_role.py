"""State snapshot publish role for ingest."""

from __future__ import annotations

from datetime import UTC, datetime

from whale.ingest.ports.message import MessagePublisherPort
from whale.ingest.usecases.dtos.message_publish_result import MessagePublishResult
from whale.ingest.usecases.dtos.state_snapshot_message import StateSnapshotMessage


class StateSnapshotPublishRole:
    """Publish one assembled snapshot message through all enabled pipelines."""

    def __init__(self, publishers: list[MessagePublisherPort]) -> None:
        """Store the publishers used during publish execution."""
        self._publishers = list(publishers)

    def publish(self, message: StateSnapshotMessage) -> list[MessagePublishResult]:
        """Publish one snapshot message through all enabled publishers."""
        results: list[MessagePublishResult] = []
        for publisher in self._publishers:
            try:
                results.append(publisher.publish_snapshot(message))
            except Exception as exc:
                results.append(
                    MessagePublishResult(
                        pipeline_name=publisher.__class__.__name__,
                        success=False,
                        message_id=message.message_id,
                        message_count=0,
                        published_at=datetime.now(tz=UTC),
                        error_message=str(exc),
                    )
                )
        return results
