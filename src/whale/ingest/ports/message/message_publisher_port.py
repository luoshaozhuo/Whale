"""Publisher ports for ingest snapshot messages."""

from __future__ import annotations

from typing import Protocol

from whale.ingest.usecases.dtos.message_publish_result import MessagePublishResult
from whale.ingest.usecases.dtos.state_snapshot_message import StateSnapshotMessage


class MessagePublisherPort(Protocol):
    """Publish one assembled state snapshot message to one pipeline."""

    def publish_snapshot(self, message: StateSnapshotMessage) -> MessagePublishResult:
        """Publish one state snapshot message."""
