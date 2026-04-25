"""Redis Streams publisher for ingest state snapshot messages."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Protocol, cast

from whale.ingest.ports.message import MessagePublisherPort
from whale.ingest.runtime.message_pipeline_settings import RedisStreamsMessageSettings
from whale.ingest.usecases.dtos.message_publish_result import MessagePublishResult
from whale.ingest.usecases.dtos.state_snapshot_message import StateSnapshotMessage


class RedisStreamsClient(Protocol):
    """Minimal Redis Streams client contract used by the publisher."""

    def xadd(
        self,
        name: str,
        fields: dict[str, str],
    ) -> str | bytes:
        """Append one entry into a Redis stream."""


class RedisStreamsMessagePublisher(MessagePublisherPort):
    """Publish snapshot messages into a Redis stream with XADD."""

    def __init__(
        self,
        settings: RedisStreamsMessageSettings,
        client: RedisStreamsClient | None = None,
    ) -> None:
        """Store settings and an optional injected Redis client."""
        self._settings = settings
        self._client = client or self._build_client(settings)

    def publish_snapshot(self, message: StateSnapshotMessage) -> MessagePublishResult:
        """Publish one snapshot message into Redis Streams."""
        record_id = self._client.xadd(
            self._settings.stream_key,
            {
                "message": message.to_json(),
                "message_id": message.message_id,
                "snapshot_id": message.snapshot_id,
                "message_type": message.message_type,
            },
        )
        return MessagePublishResult(
            pipeline_name="redis_streams",
            success=True,
            message_id=message.message_id,
            message_count=1,
            published_at=datetime.now(tz=UTC),
            error_message=None if record_id else None,
        )

    @staticmethod
    def _build_client(settings: RedisStreamsMessageSettings) -> RedisStreamsClient:
        """Build one real redis-py client lazily."""
        try:
            from redis import Redis
        except ImportError as exc:
            raise RuntimeError(
                "Redis Streams publishing requires the `redis` package to be installed."
            ) from exc

        return cast(
            RedisStreamsClient,
            Redis.from_url(
                settings.redis_url,
                decode_responses=True,
            ),
        )
