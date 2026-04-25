"""Unit tests for ingest configuration resolution."""

from __future__ import annotations

import pytest

from whale.ingest.config import (
    _default_state_cache_backend,
    _resolve_runtime_environment,
    _resolve_state_cache_backend,
)


def test_resolve_runtime_environment_defaults_to_development() -> None:
    """Default the ingest runtime environment to development."""
    assert _resolve_runtime_environment(None) == "development"
    assert _resolve_runtime_environment("") == "development"


@pytest.mark.parametrize(
    ("environment", "expected_backend"),
    [
        ("test", "sqlite"),
        ("development", "sqlite"),
        ("production", "redis"),
    ],
)
def test_default_state_cache_backend_depends_on_environment(
    environment: str,
    expected_backend: str,
) -> None:
    """Resolve one environment-specific default state-cache backend."""
    assert _default_state_cache_backend(environment) == expected_backend
    assert _resolve_state_cache_backend(environment, None) == expected_backend


def test_state_cache_backend_override_can_switch_backend() -> None:
    """Allow explicit backend overrides on top of environment defaults."""
    assert _resolve_state_cache_backend("production", "sqlite") == "sqlite"
    assert _resolve_state_cache_backend("development", "redis") == "redis"


def test_resolve_runtime_environment_rejects_unknown_value() -> None:
    """Reject unsupported runtime environments."""
    with pytest.raises(RuntimeError, match="Unsupported WHALE_INGEST_ENV value"):
        _resolve_runtime_environment("staging")


def test_resolve_state_cache_backend_rejects_unknown_value() -> None:
    """Reject unsupported state-cache backend overrides."""
    with pytest.raises(RuntimeError, match="Unsupported WHALE_INGEST_STATE_CACHE_BACKEND"):
        _resolve_state_cache_backend("development", "memory")
