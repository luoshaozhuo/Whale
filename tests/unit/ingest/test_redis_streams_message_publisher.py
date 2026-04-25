"""Unit tests for the Redis Streams snapshot publisher."""

from __future__ import annotations

from datetime import UTC, datetime

from whale.ingest.adapters.message.redis_streams_message_publisher import (
    RedisStreamsMessagePublisher,
)
from whale.ingest.runtime.message_pipeline_settings import RedisStreamsMessageSettings
from whale.ingest.usecases.dtos.state_snapshot_message import StateSnapshotMessage


class FakeRedisStreamsClient:
    """Capture Redis stream writes for tests."""

    def __init__(self) -> None:
        """Initialize one empty capture buffer."""
        self.calls: list[tuple[str, dict[str, str]]] = []

    def xadd(self, name: str, fields: dict[str, str]) -> str:
        """Capture one Redis stream append call."""
        self.calls.append((name, dict(fields)))
        return "1714032000-0"


def test_publish_snapshot_calls_xadd() -> None:
    """Publish the serialized snapshot message through Redis XADD."""
    client = FakeRedisStreamsClient()
    publisher = RedisStreamsMessagePublisher(
        settings=RedisStreamsMessageSettings(redis_url="redis://unit-test", stream_key="stream-1"),
        client=client,
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

    assert result.pipeline_name == "redis_streams"
    assert result.success is True
    assert client.calls[0][0] == "stream-1"
    assert client.calls[0][1]["message_id"] == "msg-001"
    assert '"snapshot_id":"snapshot-001"' in client.calls[0][1]["message"]
