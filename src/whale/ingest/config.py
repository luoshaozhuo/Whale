"""Python-native configuration for the ingest module."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent
SUPPORTED_ENVIRONMENTS = frozenset({"test", "development", "production"})
SUPPORTED_STATE_CACHE_BACKENDS = frozenset({"sqlite", "redis"})


def _env_path(name: str, default: str | Path) -> str | Path:
    """Return one configured path with environment override support."""
    return os.environ.get(name, default)


def _required_env(name: str) -> str:
    """Return one required environment variable or raise a clear error."""
    value = os.environ.get(name)
    if value is None:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value


def _optional_env(name: str) -> str | None:
    """Return one optional environment variable.

    Empty strings are treated as missing values.
    """
    value = os.environ.get(name)
    if value == "":
        return None
    return value


def _optional_env_int(name: str) -> int | None:
    """Return one optional integer environment variable."""
    value = _optional_env(name)
    if value is None:
        return None
    return int(value)


def _optional_env_bool(name: str) -> bool | None:
    """Return one optional boolean environment variable."""
    value = _optional_env(name)
    if value is None:
        return None
    return value.lower() != "false"


def _resolve_runtime_environment(value: str | None) -> str:
    """Resolve the ingest runtime environment.

    Defaults to `development` when unset.
    """
    if value in (None, ""):
        environment = "development"
    else:
        environment_text = value
        assert environment_text is not None
        environment = environment_text.strip().lower()
    if environment not in SUPPORTED_ENVIRONMENTS:
        raise RuntimeError(
            "Unsupported WHALE_INGEST_ENV value: "
            f"{value!r}. Expected one of {sorted(SUPPORTED_ENVIRONMENTS)}."
        )
    return environment


def _default_state_cache_backend(environment: str) -> str:
    """Return the default state-cache backend for one runtime environment."""
    return "redis" if environment == "production" else "sqlite"


def _resolve_state_cache_backend(
    environment: str,
    override: str | None,
) -> str:
    """Resolve the state-cache backend with optional explicit override."""
    if override in (None, ""):
        backend = _default_state_cache_backend(environment)
    else:
        override_text = override
        assert override_text is not None
        backend = override_text.strip().lower()
    if backend not in SUPPORTED_STATE_CACHE_BACKENDS:
        raise RuntimeError(
            "Unsupported WHALE_INGEST_STATE_CACHE_BACKEND value: "
            f"{override!r}. Expected one of {sorted(SUPPORTED_STATE_CACHE_BACKENDS)}."
        )
    return backend


@dataclass(frozen=True, slots=True)
class DatabaseConfig:
    """Database-related configuration for ingest."""

    drivername: str
    host: str | None
    port: int | None
    database: str | Path
    username: str | None
    password: str | None
    pool_size: int
    max_overflow: int
    pool_timeout: int
    pool_recycle: int
    pool_pre_ping: bool


@dataclass(frozen=True, slots=True)
class OpcUaConfig:
    """OPC UA source file configuration for ingest."""

    connection_config_path: str
    nodeset_path: str


@dataclass(frozen=True, slots=True)
class RedisStateCacheConfig:
    """Redis latest-state cache configuration for ingest."""

    host: str | None
    port: int | None
    db: int | None
    username: str | None
    password: str | None
    hash_key: str | None
    station_id: str | None
    decode_responses: bool | None


@dataclass(frozen=True, slots=True)
class Config:
    """Top-level ingest configuration."""

    environment: str
    state_cache_backend: str
    database: DatabaseConfig
    opcua: OpcUaConfig
    redis_state_cache: RedisStateCacheConfig


_RUNTIME_ENVIRONMENT = _resolve_runtime_environment(os.environ.get("WHALE_INGEST_ENV"))

CONFIG = Config(
    environment=_RUNTIME_ENVIRONMENT,
    state_cache_backend=_resolve_state_cache_backend(
        _RUNTIME_ENVIRONMENT,
        os.environ.get("WHALE_INGEST_STATE_CACHE_BACKEND"),
    ),
    database=DatabaseConfig(
        drivername="sqlite",  # for postgre, postgresql+psycopg2
        host=None,  # for postgre, localhost
        port=None,  # for postgre, 5432
        database=_env_path("WHALE_INGEST_DB_PATH", PROJECT_ROOT / "whale.db"),
        username=None,  # for postgre, os.environ.get("WHALE_DB_USERNAME")
        password=None,  # for postgre, os.environ.get("WHALE_DB_PASSWORD")
        pool_size=10,
        max_overflow=20,
        pool_timeout=30,
        pool_recycle=3600,
        pool_pre_ping=True,
    ),
    opcua=OpcUaConfig(
        connection_config_path=str(
            _env_path(
                "WHALE_INGEST_OPCUA_CONNECTION_CONFIG_PATH",
                "tools/opcua_sim/templates/OPCUA_client_connections.yaml",
            )
        ),
        nodeset_path=str(
            _env_path(
                "WHALE_INGEST_OPCUA_NODESET_PATH",
                "tools/opcua_sim/templates/OPCUANodeSet.xml",
            )
        ),
    ),
    redis_state_cache=RedisStateCacheConfig(
        host=_optional_env("WHALE_INGEST_REDIS_HOST"),
        port=_optional_env_int("WHALE_INGEST_REDIS_PORT"),
        db=_optional_env_int("WHALE_INGEST_REDIS_DB"),
        username=_optional_env("WHALE_INGEST_REDIS_USERNAME"),
        password=_optional_env("WHALE_INGEST_REDIS_PASSWORD"),
        hash_key=_optional_env("WHALE_INGEST_REDIS_STATE_HASH_KEY"),
        station_id=_optional_env("WHALE_INGEST_STATION_ID"),
        decode_responses=_optional_env_bool("WHALE_INGEST_REDIS_DECODE_RESPONSES"),
    ),
)
