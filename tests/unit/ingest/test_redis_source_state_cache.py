"""Unit tests for the Redis-backed latest-state cache."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from whale.ingest.adapters.state.redis_source_state_cache import (
    RedisSourceStateCache,
    RedisSourceStateCacheSettings,
)
from whale.ingest.usecases.dtos.acquired_node_state import AcquiredNodeState


class FakeRedisPipeline:
    """Simple in-memory Redis pipeline fake used by unit tests."""

    def __init__(self, client: FakeRedisHashClient) -> None:
        self._client = client
        self._commands: list[tuple[str, str, str]] = []

    def hset(self, name: str, key: str, value: str) -> None:
        self._commands.append((name, key, value))

    def execute(self) -> None:
        for name, key, value in self._commands:
            self._client.hset(name, key, value)
        self._commands.clear()


class FakeRedisHashClient:
    """Simple in-memory Redis hash fake used by unit tests."""

    def __init__(self) -> None:
        """Initialize one empty hash store."""
        self.hashes: dict[str, dict[str, str]] = {}

    def hset(self, name: str, key: str, value: str) -> int:
        """Upsert one hash field."""
        bucket = self.hashes.setdefault(name, {})
        is_new = key not in bucket
        bucket[key] = value
        return 1 if is_new else 0

    def hgetall(self, name: str) -> dict[str, str]:
        """Return all fields from one hash."""
        return dict(self.hashes.get(name, {}))

    def pipeline(self) -> FakeRedisPipeline:
        """Return a pipeline that batches hset commands."""
        return FakeRedisPipeline(self)


def _build_settings() -> RedisSourceStateCacheSettings:
    """Build deterministic Redis cache settings for tests."""
    return RedisSourceStateCacheSettings(
        host="127.0.0.1",
        port=6379,
        db=0,
        username=None,
        password=None,
        hash_key="whale:ingest:state",
        station_id="station-001",
    )


def test_store_many_upserts_one_latest_state_per_station_device_model_variable() -> None:
    """Keep one latest Redis hash field per station, device, model and variable."""
    client = FakeRedisHashClient()
    repository = RedisSourceStateCache(settings=_build_settings(), client=client)
    first_observed_at = datetime(2026, 4, 25, 10, 0, tzinfo=UTC)
    second_observed_at = first_observed_at.replace(minute=1)

    processed_first = repository.store_many(
        "model_1",
        [
            AcquiredNodeState(
                source_id="WTG_01",
                node_key="TotW",
                value="1200.0",
                observed_at=first_observed_at,
            )
        ],
    )
    processed_second = repository.store_many(
        "model_1",
        [
            AcquiredNodeState(
                source_id="WTG_01",
                node_key="TotW",
                value="1250.0",
                observed_at=second_observed_at,
            )
        ],
    )

    assert processed_first == 1
    assert processed_second == 1
    assert list(client.hashes["whale:ingest:state"]) == ["station-001:WTG_01:model_1:TotW"]

    snapshot = repository.read_snapshot()
    assert len(snapshot) == 1
    assert snapshot[0].station_id == "station-001"
    assert snapshot[0].device_code == "WTG_01"
    assert snapshot[0].model_id == "model_1"
    assert snapshot[0].variable_key == "TotW"
    assert snapshot[0].value == "1250.0"
    assert snapshot[0].source_observed_at == second_observed_at


def test_read_snapshot_returns_full_current_latest_state_cache() -> None:
    """Read the full latest-state snapshot from the Redis hash."""
    client = FakeRedisHashClient()
    repository = RedisSourceStateCache(settings=_build_settings(), client=client)
    observed_at = datetime(2026, 4, 25, 10, 0, tzinfo=UTC)

    repository.store_many(
        "model_1",
        [
            AcquiredNodeState(
                source_id="WTG_01",
                node_key="Spd",
                value="9.5",
                observed_at=observed_at,
            ),
            AcquiredNodeState(
                source_id="WTG_01",
                node_key="TotW",
                value="1200.0",
                observed_at=observed_at,
            ),
        ],
    )

    snapshot = repository.read_snapshot()

    assert [(row.device_code, row.variable_key) for row in snapshot] == [
        ("WTG_01", "Spd"),
        ("WTG_01", "TotW"),
    ]
    assert [row.station_id for row in snapshot] == ["station-001", "station-001"]
    assert [row.id for row in snapshot] == [1, 2]


def test_build_client_can_use_installed_redis_package_without_server() -> None:
    """Construct one real redis-py client without requiring a running server."""
    pytest.importorskip("redis")

    repository = RedisSourceStateCache(settings=_build_settings())

    assert hasattr(repository._client, "hset")  # noqa: SLF001
    assert hasattr(repository._client, "hgetall")  # noqa: SLF001
