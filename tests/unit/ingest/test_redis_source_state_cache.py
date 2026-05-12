"""Unit tests for the Redis-backed latest-state cache."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from whale.ingest.adapters.state.redis_source_state_cache import (
    RedisSourceStateCache,
    RedisSourceStateCacheSettings,
)
from whale.ingest.usecases.dtos.acquired_node_state import (
    AcquiredNodeStateBatch,
    AcquiredNodeValue,
)


class FakeRedisPipeline:
    def __init__(self, client: "FakeRedisHashClient") -> None:
        self._client = client
        self._commands: list[tuple[str, str, str]] = []

    def hset(self, name: str, key: str, value: str) -> None:
        self._commands.append((name, key, value))

    def execute(self) -> None:
        for name, key, value in self._commands:
            self._client.hset(name, key, value)
        self._commands.clear()


class FakeRedisHashClient:
    def __init__(self) -> None:
        self.hashes: dict[str, dict[str, str]] = {}

    def hset(self, name: str, key: str, value: str) -> int:
        bucket = self.hashes.setdefault(name, {})
        is_new = key not in bucket
        bucket[key] = value
        return 1 if is_new else 0

    def hget(self, name: str, key: str) -> str | None:
        return self.hashes.get(name, {}).get(key)

    def hgetall(self, name: str) -> dict[str, str]:
        return dict(self.hashes.get(name, {}))

    def pipeline(self) -> FakeRedisPipeline:
        return FakeRedisPipeline(self)


def _build_settings() -> RedisSourceStateCacheSettings:
    return RedisSourceStateCacheSettings(
        host="127.0.0.1",
        port=6379,
        db=0,
        username=None,
        password=None,
        hash_key="whale:ingest:state",
        station_id="station-001",
    )


def _build_batch(
    *,
    observed_at: datetime,
    value: str,
    server_timestamp: datetime | None = None,
    availability_status: str = "VALID",
) -> AcquiredNodeStateBatch:
    return AcquiredNodeStateBatch(
        source_id="LD_01",
        batch_observed_at=observed_at,
        client_received_at=observed_at,
        client_processed_at=observed_at,
        values=[
            AcquiredNodeValue(
                node_key="TotW",
                value=value,
                quality="Good",
                server_timestamp=server_timestamp,
            )
        ],
        availability_status=availability_status,
    )


def test_update_and_read_snapshot_return_ld_level_state() -> None:
    client = FakeRedisHashClient()
    cache = RedisSourceStateCache(settings=_build_settings(), client=client)
    now = datetime(2026, 4, 25, 10, 0, tzinfo=UTC)

    updated = cache.update(
        ld_name="LD_01",
        batch=AcquiredNodeStateBatch(
            source_id="LD_01",
            batch_observed_at=now,
            client_received_at=now,
            client_processed_at=now,
            values=[
                AcquiredNodeValue(node_key="Spd", value="9.5"),
                AcquiredNodeValue(node_key="TotW", value="1200.0"),
            ],
        ),
    )

    snapshot = cache.read_snapshot()

    assert updated == 2
    assert len(snapshot) == 1
    assert snapshot[0].ld_name == "LD_01"
    assert snapshot[0].source_id == "LD_01"
    assert snapshot[0].availability_status == "VALID"
    assert [value.node_key for value in snapshot[0].values] == ["Spd", "TotW"]


def test_older_server_timestamp_does_not_overwrite_newer_value() -> None:
    client = FakeRedisHashClient()
    cache = RedisSourceStateCache(settings=_build_settings(), client=client)
    now = datetime(2026, 4, 25, 10, 0, tzinfo=UTC)

    first = _build_batch(
        observed_at=now,
        value="1250.0",
        server_timestamp=now + timedelta(seconds=5),
    )
    second = _build_batch(
        observed_at=now + timedelta(seconds=10),
        value="1200.0",
        server_timestamp=now,
    )

    assert cache.update(ld_name="LD_01", batch=first) == 1
    assert cache.update(ld_name="LD_01", batch=second) == 0

    snapshot = cache.read_snapshot()
    assert snapshot[0].values[0].value == "1250.0"


def test_mark_unavailable_and_mark_alive_only_change_status() -> None:
    client = FakeRedisHashClient()
    cache = RedisSourceStateCache(settings=_build_settings(), client=client)
    now = datetime(2026, 4, 25, 10, 0, tzinfo=UTC)

    cache.update(ld_name="LD_01", batch=_build_batch(observed_at=now, value="1200.0"))
    cache.mark_unavailable(
        ld_name="LD_01",
        status="OFFLINE",
        observed_at=now + timedelta(seconds=5),
        reason="connection lost",
    )

    offline_snapshot = cache.read_snapshot()
    assert offline_snapshot[0].availability_status == "OFFLINE"
    assert offline_snapshot[0].unavailable_reason == "connection lost"
    assert offline_snapshot[0].values[0].value == "1200.0"

    cache.mark_alive(ld_name="LD_01", observed_at=now + timedelta(seconds=10))

    alive_snapshot = cache.read_snapshot()
    assert alive_snapshot[0].availability_status == "VALID"
    assert alive_snapshot[0].unavailable_reason is None
    assert alive_snapshot[0].values[0].value == "1200.0"


def test_build_client_can_use_installed_redis_package_without_server() -> None:
    pytest.importorskip("redis")

    cache = RedisSourceStateCache(settings=_build_settings())

    assert hasattr(cache._client, "hset")  # noqa: SLF001
    assert hasattr(cache._client, "hgetall")  # noqa: SLF001
