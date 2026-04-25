"""Redis-backed latest-state cache for ingest."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol, cast

from whale.ingest.config import CONFIG, RedisStateCacheConfig
from whale.ingest.ports.state import (
    SourceStateCachePort,
    SourceStateSnapshotReaderPort,
)
from whale.ingest.usecases.dtos.acquired_node_state import AcquiredNodeState
from whale.ingest.usecases.dtos.cached_source_state import CachedSourceState


class RedisHashClient(Protocol):
    """Minimal Redis hash client contract used by the Redis state cache."""

    def hset(self, name: str, key: str, value: str) -> int:
        """Set one hash field."""

    def hgetall(self, name: str) -> Mapping[str, str]:
        """Return all hash fields and values."""


@dataclass(frozen=True, slots=True)
class RedisSourceStateCacheSettings:
    """Connection and key settings for the Redis latest-state cache."""

    host: str
    port: int
    db: int
    username: str | None
    password: str | None
    hash_key: str
    station_id: str
    decode_responses: bool = True

    @classmethod
    def from_config(
        cls,
        config: RedisStateCacheConfig,
    ) -> RedisSourceStateCacheSettings:
        """Build adapter settings from the ingest module config."""
        missing_names = [
            name
            for name, value in (
                ("WHALE_INGEST_REDIS_HOST", config.host),
                ("WHALE_INGEST_REDIS_PORT", config.port),
                ("WHALE_INGEST_REDIS_DB", config.db),
                ("WHALE_INGEST_REDIS_STATE_HASH_KEY", config.hash_key),
                ("WHALE_INGEST_STATION_ID", config.station_id),
                ("WHALE_INGEST_REDIS_DECODE_RESPONSES", config.decode_responses),
            )
            if value is None
        ]
        if missing_names:
            raise RuntimeError(
                "Missing required Redis state cache environment variables: "
                + ", ".join(missing_names)
            )
        assert config.host is not None
        assert config.port is not None
        assert config.db is not None
        assert config.hash_key is not None
        assert config.station_id is not None
        assert config.decode_responses is not None
        return cls(
            host=config.host,
            port=config.port,
            db=config.db,
            username=config.username,
            password=config.password,
            hash_key=config.hash_key,
            station_id=config.station_id,
            decode_responses=config.decode_responses,
        )


class RedisSourceStateCache(SourceStateCachePort, SourceStateSnapshotReaderPort):
    """Use one Redis hash as the production-recommended latest-state cache."""

    def __init__(
        self,
        settings: RedisSourceStateCacheSettings | None = None,
        client: RedisHashClient | None = None,
    ) -> None:
        """Create the Redis-backed state cache.

        Args:
            settings: Redis connection and key settings.
            client: Optional injected Redis client used by tests or callers that
                manage their own Redis connection lifecycle.
        """
        self._settings = settings or RedisSourceStateCacheSettings.from_config(
            CONFIG.redis_state_cache
        )
        self._client = client or self._build_client(self._settings)

    def store_many(
        self,
        model_id: str,
        acquired_states: list[AcquiredNodeState],
    ) -> int:
        """Upsert latest-state rows into the Redis hash cache."""
        if not acquired_states:
            return 0

        received_at = datetime.now(tz=UTC)
        for state in acquired_states:
            field = self._build_field_name(
                station_id=self._settings.station_id,
                device_code=state.source_id,
                model_id=model_id,
                variable_key=state.node_key,
            )
            payload = json.dumps(
                {
                    "station_id": self._settings.station_id,
                    "device_code": state.source_id,
                    "model_id": model_id,
                    "variable_key": state.node_key,
                    "value": state.value,
                    "source_observed_at": state.observed_at.isoformat(),
                    "received_at": received_at.isoformat(),
                    "updated_at": received_at.isoformat(),
                }
            )
            self._client.hset(self._settings.hash_key, field, payload)
        return len(acquired_states)

    def read_snapshot(self) -> list[CachedSourceState]:
        """Return the full current latest-state snapshot from Redis."""
        raw_rows = self._client.hgetall(self._settings.hash_key)
        parsed_rows: list[CachedSourceState] = []

        for row_id, (_, raw_payload) in enumerate(
            sorted(raw_rows.items(), key=lambda item: self._decode_value(item[0])),
            start=1,
        ):
            payload = json.loads(self._decode_value(raw_payload))
            parsed_rows.append(
                CachedSourceState(
                    id=row_id,
                    station_id=payload.get("station_id"),
                    device_code=str(payload["device_code"]),
                    model_id=str(payload["model_id"]),
                    variable_key=str(payload["variable_key"]),
                    value=self._optional_str(payload.get("value")),
                    source_observed_at=self._parse_datetime(payload.get("source_observed_at")),
                    received_at=self._parse_datetime(payload.get("received_at")),
                    updated_at=self._parse_datetime(payload.get("updated_at")),
                )
            )

        return parsed_rows

    @staticmethod
    def _build_client(settings: RedisSourceStateCacheSettings) -> RedisHashClient:
        """Build one real Redis client lazily so tests can inject a fake client."""
        try:
            from redis import Redis
        except ImportError as exc:
            raise RuntimeError(
                "Redis support requires the `redis` package to be installed."
            ) from exc

        return cast(
            RedisHashClient,
            Redis(
                host=settings.host,
                port=settings.port,
                db=settings.db,
                username=settings.username,
                password=settings.password,
                decode_responses=settings.decode_responses,
            ),
        )

    @staticmethod
    def _build_field_name(
        *,
        station_id: str,
        device_code: str,
        model_id: str,
        variable_key: str,
    ) -> str:
        """Build the Redis hash field name for one cached variable state."""
        return f"{station_id}:{device_code}:{model_id}:{variable_key}"

    @staticmethod
    def _decode_value(value: object) -> str:
        """Decode one Redis field name or value into text."""
        if isinstance(value, bytes):
            return value.decode("utf-8")
        return str(value)

    @staticmethod
    def _parse_datetime(value: object) -> datetime | None:
        """Parse one ISO datetime value if present."""
        if value is None:
            return None
        return datetime.fromisoformat(str(value))

    @staticmethod
    def _optional_str(value: object) -> str | None:
        """Return one optional string value."""
        if value is None:
            return None
        return str(value)
