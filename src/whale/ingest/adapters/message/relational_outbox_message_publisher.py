"""Relational outbox publisher for ingest state snapshot messages."""

from __future__ import annotations

from datetime import UTC, datetime

from whale.ingest.framework.persistence.orm.state_snapshot_outbox_orm import (
    StateSnapshotOutboxORM,
)
from whale.ingest.framework.persistence.session import session_scope
from whale.ingest.ports.message import MessagePublisherPort
from whale.ingest.usecases.dtos.message_publish_result import MessagePublishResult
from whale.ingest.usecases.dtos.state_snapshot_message import StateSnapshotMessage


class RelationalOutboxMessagePublisher(MessagePublisherPort):
    """Persist snapshot messages into the ingest relational outbox table."""

    def publish_snapshot(self, message: StateSnapshotMessage) -> MessagePublishResult:
        """Write one snapshot message into the relational outbox."""
        with session_scope() as session:
            session.add(
                StateSnapshotOutboxORM(
                    message_id=message.message_id,
                    snapshot_id=message.snapshot_id,
                    schema_version=message.schema_version,
                    message_type=message.message_type,
                    payload=message.to_json(),
                    snapshot_at=message.snapshot_at,
                )
            )
            session.commit()

        return MessagePublishResult(
            pipeline_name="relational_outbox",
            success=True,
            message_id=message.message_id,
            message_count=1,
            published_at=datetime.now(tz=UTC),
        )
