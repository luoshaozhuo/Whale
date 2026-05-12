"""Unit tests for the Kafka snapshot publisher."""

from __future__ import annotations

from datetime import UTC, datetime

from whale.ingest.adapters.message.kafka_message_publisher import KafkaMessagePublisher
from whale.ingest.ports.message.message_publisher_port import StateSnapshotMessage
from whale.ingest.runtime.message_pipeline_settings import KafkaMessageSettings


class FakeKafkaFuture:
    """Capture `get()` calls on the Kafka send future."""

    def __init__(self) -> None:
        """Initialize one empty timeout capture."""
        self.timeouts: list[float | None] = []

    def get(self, timeout: float | None = None) -> object:
        """Capture the requested timeout and return one fake metadata object."""
        self.timeouts.append(timeout)
        return {"topic": "topic-1"}


class FakeKafkaProducer:
    """Capture Kafka producer sends for tests."""

    def __init__(self) -> None:
        """Initialize capture buffers."""
        self.calls: list[tuple[str, bytes, bytes]] = []
        self.flush_count = 0
        self.future = FakeKafkaFuture()

    def send(self, topic: str, key: bytes, value: bytes) -> FakeKafkaFuture:
        """Capture one Kafka send call."""
        self.calls.append((topic, key, value))
        return self.future

    def flush(self) -> None:
        """Capture Kafka flush calls."""
        self.flush_count += 1


def test_publish_snapshot_calls_kafka_send() -> None:
    """Publish the serialized snapshot message through Kafka send()."""
    producer = FakeKafkaProducer()
    publisher = KafkaMessagePublisher(
        settings=KafkaMessageSettings(
            bootstrap_servers=("kafka:9092",),
            topic="topic-1",
            ack_timeout_seconds=3.0,
        ),
        producer=producer,
    )
    message = StateSnapshotMessage(
        message_id="msg-001",
        schema_version="v1",
        message_type="STATE_SNAPSHOT",
        source_module="ingest",
        snapshot_id="snapshot-001",
        snapshot_at=datetime(2026, 4, 25, 10, 0, tzinfo=UTC),
        item_count=0,
        items=[],
    )

    result = publisher.publish_snapshot(message)

    assert result.pipeline_name == "kafka"
    assert result.success is True
    assert producer.calls[0][0] == "topic-1"
    assert producer.calls[0][1] == b"snapshot-001"
    assert b'"message_id":"msg-001"' in producer.calls[0][2]
    assert producer.future.timeouts == [3.0]
    assert producer.flush_count == 1
