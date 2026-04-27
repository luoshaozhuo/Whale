"""Unit tests for the state snapshot emit use case."""

from __future__ import annotations

from datetime import UTC, datetime

from whale.ingest.usecases.dtos.cached_source_state import CachedSourceState
from whale.ingest.usecases.dtos.message_publish_result import MessagePublishResult
from whale.ingest.usecases.dtos.state_snapshot_message import StateSnapshotMessage
from whale.ingest.usecases.emit_state_snapshot_usecase import EmitStateSnapshotUseCase


class FakeSourceStateSnapshotReaderPort:
    """Return a prebuilt latest-state snapshot for tests."""

    def __init__(self, snapshot: list[CachedSourceState]) -> None:
        """Store the snapshot returned by the fake reader."""
        self._snapshot = list(snapshot)

    def read_snapshot(self) -> list[CachedSourceState]:
        """Return the configured latest-state snapshot."""
        return list(self._snapshot)


class CapturingPublisher:
    """Capture published snapshot messages and return successful results."""

    def __init__(self, pipeline_name: str) -> None:
        """Store the pipeline name and capture buffer."""
        self.pipeline_name = pipeline_name
        self.messages: list[StateSnapshotMessage] = []

    def publish_snapshot(self, message: StateSnapshotMessage) -> MessagePublishResult:
        """Capture the published message and return one success result."""
        self.messages.append(message)
        return MessagePublishResult(
            pipeline_name=self.pipeline_name,
            success=True,
            message_id=message.message_id,
            message_count=1,
            published_at=datetime(2026, 4, 25, 10, 0, tzinfo=UTC),
        )


class FailingPublisher:
    """Raise one publishing error to verify fault isolation."""

    def publish_snapshot(self, message: StateSnapshotMessage) -> MessagePublishResult:
        """Raise one deterministic exception."""
        del message
        raise RuntimeError("publisher boom")


def _build_snapshot() -> list[CachedSourceState]:
    """Build one deterministic latest-state snapshot."""
    observed_at = datetime(2026, 4, 25, 10, 0, tzinfo=UTC)
    return [
        CachedSourceState(
            id=1,
            station_id="station-001",
            device_code="WTG_01",
            model_id="model_1",
            variable_key="TotW",
            value="1200.0",
            source_observed_at=observed_at,
            received_at=observed_at,
            updated_at=observed_at,
        )
    ]


def test_execute_reads_snapshot_and_publishes_assembled_message() -> None:
    """Read the snapshot, assemble one message, and publish it."""
    publisher = CapturingPublisher("relational_outbox")
    use_case = EmitStateSnapshotUseCase(
        snapshot_reader_port=FakeSourceStateSnapshotReaderPort(_build_snapshot()),
        publisher=publisher,
    )

    result = use_case.execute()

    assert result.success is True
    assert len(publisher.messages) == 1
    message = publisher.messages[0]
    assert message.message_type == "STATE_SNAPSHOT"
    assert message.source_module == "ingest"
    assert message.item_count == 1
    assert message.items[0].station_id == "station-001"
    assert message.items[0].device_code == "WTG_01"
    assert message.items[0].variable_key == "TotW"


def test_execute_builds_valid_message_for_empty_snapshot() -> None:
    """Build and publish one empty-but-valid snapshot message."""
    publisher = CapturingPublisher("relational_outbox")
    use_case = EmitStateSnapshotUseCase(
        snapshot_reader_port=FakeSourceStateSnapshotReaderPort([]),
        publisher=publisher,
    )

    result = use_case.execute()

    assert result.success is True
    message = publisher.messages[0]
    assert message.item_count == 0
    assert message.items == []


def test_execute_uses_one_selected_publisher() -> None:
    """Publish one snapshot through the configured publisher only."""
    publisher = CapturingPublisher("redis_streams")
    use_case = EmitStateSnapshotUseCase(
        snapshot_reader_port=FakeSourceStateSnapshotReaderPort(_build_snapshot()),
        publisher=publisher,
    )

    result = use_case.execute()

    assert result.pipeline_name == "redis_streams"
    assert result.success is True
    assert len(publisher.messages) == 1


def test_execute_returns_failure_result_when_publisher_raises() -> None:
    """Return one failure result when the configured publisher raises."""
    use_case = EmitStateSnapshotUseCase(
        snapshot_reader_port=FakeSourceStateSnapshotReaderPort(_build_snapshot()),
        publisher=FailingPublisher(),
    )

    result = use_case.execute()

    assert result.success is False
    assert result.error_message == "publisher boom"
