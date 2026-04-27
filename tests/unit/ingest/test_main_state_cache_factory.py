"""Unit tests for ingest runtime state-cache adapter selection."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from whale.ingest.__main__ import _build_message_publisher, _build_state_cache_port
from whale.ingest.adapters.state.sqlite_source_state_cache import SqliteSourceStateCache
from whale.ingest.config import KafkaMessageConfig, RedisStreamsMessageConfig


def test_build_state_cache_port_uses_relational_backend_when_configured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Build the SQLite-backed local state cache when configured as relational."""
    monkeypatch.setattr(
        "whale.ingest.__main__.CONFIG",
        SimpleNamespace(state_cache_backend="relational"),
    )

    state_cache = _build_state_cache_port()

    assert isinstance(state_cache, SqliteSourceStateCache)


def test_build_state_cache_port_uses_redis_backend_when_configured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Build the Redis state cache when the backend is configured as redis."""
    monkeypatch.setattr(
        "whale.ingest.__main__.CONFIG",
        SimpleNamespace(state_cache_backend="redis"),
    )

    class FakeRedisSourceStateCache:
        """Test double used to avoid constructing a real Redis client."""

    monkeypatch.setattr(
        "whale.ingest.__main__.RedisSourceStateCache",
        FakeRedisSourceStateCache,
    )

    state_cache = _build_state_cache_port()

    assert isinstance(state_cache, FakeRedisSourceStateCache)


def test_build_state_cache_port_rejects_unknown_backend(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Reject unsupported state-cache backends in runtime assembly."""
    monkeypatch.setattr(
        "whale.ingest.__main__.CONFIG",
        SimpleNamespace(state_cache_backend="memory"),
    )

    with pytest.raises(RuntimeError, match="Unsupported state cache backend configured"):
        _build_state_cache_port()


def test_build_message_publisher_uses_kafka_backend_when_configured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Build the Kafka message publisher when kafka backend is configured."""

    class FakeKafkaMessagePublisher:
        """Test double used to avoid constructing a real Kafka producer."""

        def __init__(self, settings: object) -> None:
            """Store settings passed by the builder."""
            self.settings = settings

    monkeypatch.setattr(
        "whale.ingest.__main__.CONFIG",
        SimpleNamespace(
            message=KafkaMessageConfig(
                bootstrap_servers=("127.0.0.1:9092",),
                topic="topic-1",
                ack_timeout_seconds=5.0,
            )
        ),
    )
    monkeypatch.setattr("whale.ingest.__main__.KafkaMessagePublisher", FakeKafkaMessagePublisher)

    publisher = _build_message_publisher()

    assert isinstance(publisher, FakeKafkaMessagePublisher)


def test_build_message_publisher_uses_redis_streams_backend_when_configured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Build the Redis Streams publisher when redis_streams backend is configured."""

    class FakeRedisStreamsMessagePublisher:
        """Test double used to avoid constructing a real Redis client."""

        def __init__(self, settings: object) -> None:
            """Store settings passed by the builder."""
            self.settings = settings

    monkeypatch.setattr(
        "whale.ingest.__main__.CONFIG",
        SimpleNamespace(
            message=RedisStreamsMessageConfig(
                redis_url="redis://127.0.0.1:6379/0",
                stream_key="stream-1",
            )
        ),
    )
    monkeypatch.setattr(
        "whale.ingest.__main__.RedisStreamsMessagePublisher",
        FakeRedisStreamsMessagePublisher,
    )

    publisher = _build_message_publisher()

    assert isinstance(publisher, FakeRedisStreamsMessagePublisher)
