"""Use case for reading and publishing full latest-state snapshots."""

from __future__ import annotations

from whale.ingest.ports.message import MessagePublisherPort
from whale.ingest.ports.state import SourceStateSnapshotReaderPort
from whale.ingest.usecases.dtos.message_publish_result import MessagePublishResult
from whale.ingest.usecases.roles.state_snapshot_message_assembler import (
    StateSnapshotMessageAssembler,
)
from whale.ingest.usecases.roles.state_snapshot_publish_role import (
    StateSnapshotPublishRole,
)
from whale.ingest.usecases.roles.state_snapshot_read_role import StateSnapshotReadRole


class EmitStateSnapshotUseCase:
    """Read the current full snapshot and publish it through the configured backend."""

    def __init__(
        self,
        snapshot_reader_port: SourceStateSnapshotReaderPort,
        publisher: MessagePublisherPort,
    ) -> None:
        """Store the snapshot-reader and publisher dependencies."""
        self._read_role = StateSnapshotReadRole(snapshot_reader_port)
        self._assembler = StateSnapshotMessageAssembler()
        self._publish_role = StateSnapshotPublishRole(publisher)

    def execute(self) -> MessagePublishResult:
        """Read, assemble, and publish the current full latest-state snapshot."""
        snapshot = self._read_role.read_snapshot()
        message = self._assembler.assemble(snapshot)
        return self._publish_role.publish(message)
