"""Unit tests for ingest runtime state-cache adapter selection."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from whale.ingest.__main__ import _build_state_cache_port
from whale.ingest.adapters.state.sqlite_source_state_cache import SqliteSourceStateCache


def test_build_state_cache_port_uses_sqlite_backend_when_configured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Build the SQLite state cache when the backend is configured as sqlite."""
    monkeypatch.setattr(
        "whale.ingest.__main__.CONFIG",
        SimpleNamespace(state_cache_backend="sqlite"),
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
