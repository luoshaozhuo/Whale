"""Message pipeline settings for ingest snapshot publishing."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


def _split_csv_env(name: str, default: tuple[str, ...] = ()) -> tuple[str, ...]:
    """Split one comma-separated environment variable into a tuple."""
    raw = os.environ.get(name)
    if raw is None or raw == "":
        return default
    return tuple(item.strip() for item in raw.split(",") if item.strip())


@dataclass(frozen=True, slots=True)
class FileOutboxMessageSettings:
    """Settings for file outbox snapshot publishing."""

    output_root: Path = Path("data/outbox")


@dataclass(frozen=True, slots=True)
class RedisStreamsMessageSettings:
    """Settings for Redis Streams snapshot publishing."""

    redis_url: str = "redis://127.0.0.1:6379/0"
    stream_key: str = "whale:ingest:state_snapshot:v1"


@dataclass(frozen=True, slots=True)
class KafkaMessageSettings:
    """Settings for Kafka snapshot publishing."""

    bootstrap_servers: tuple[str, ...] = ("127.0.0.1:9092",)
    topic: str = "whale.ingest.state_snapshot.v1"
    ack_timeout_seconds: float = 5.0


@dataclass(frozen=True, slots=True)
class MessagePipelineSettings:
    """Top-level settings for enabled snapshot publish pipelines."""

    enabled_pipelines: tuple[str, ...] = field(default_factory=tuple)
    file_outbox: FileOutboxMessageSettings = field(default_factory=FileOutboxMessageSettings)
    redis_streams: RedisStreamsMessageSettings = field(default_factory=RedisStreamsMessageSettings)
    kafka: KafkaMessageSettings = field(default_factory=KafkaMessageSettings)

    @classmethod
    def from_env(cls) -> MessagePipelineSettings:
        """Build message pipeline settings from environment variables."""
        return cls(
            enabled_pipelines=_split_csv_env("WHALE_INGEST_ENABLED_MESSAGE_PIPELINES"),
            file_outbox=FileOutboxMessageSettings(
                output_root=Path(
                    os.environ.get(
                        "WHALE_INGEST_FILE_OUTBOX_PATH",
                        "data/outbox",
                    )
                )
            ),
            redis_streams=RedisStreamsMessageSettings(
                redis_url=os.environ.get(
                    "WHALE_INGEST_MESSAGE_REDIS_URL",
                    "redis://127.0.0.1:6379/0",
                ),
                stream_key=os.environ.get(
                    "WHALE_INGEST_MESSAGE_REDIS_STREAM_KEY",
                    "whale:ingest:state_snapshot:v1",
                ),
            ),
            kafka=KafkaMessageSettings(
                bootstrap_servers=_split_csv_env(
                    "WHALE_INGEST_KAFKA_BOOTSTRAP_SERVERS",
                    ("127.0.0.1:9092",),
                ),
                topic=os.environ.get(
                    "WHALE_INGEST_KAFKA_TOPIC",
                    "whale.ingest.state_snapshot.v1",
                ),
                ack_timeout_seconds=float(
                    os.environ.get(
                        "WHALE_INGEST_KAFKA_ACK_TIMEOUT_SECONDS",
                        "5.0",
                    )
                ),
            ),
        )
