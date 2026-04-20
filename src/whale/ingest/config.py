"""Python-native configuration for the ingest module."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent


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
class Config:
    """Top-level ingest configuration."""

    database: DatabaseConfig
    opcua: OpcUaConfig


CONFIG = Config(
    database=DatabaseConfig(
        drivername="sqlite",  # for postgre, postgresql+psycopg2
        host=None,  # for postgre, localhost
        port=None,  # for postgre, 5432
        database=PROJECT_ROOT / "whale.db",  # for postgre, whale
        username=None,  # for postgre, os.environ.get("WHALE_DB_USERNAME")
        password=None,  # for postgre, os.environ.get("WHALE_DB_PASSWORD")
        pool_size=10,
        max_overflow=20,
        pool_timeout=30,
        pool_recycle=3600,
        pool_pre_ping=True,
    ),
    opcua=OpcUaConfig(
        connection_config_path="tools/opcua_sim/templates/OPCUA_client_connections.yaml",
        nodeset_path="tools/opcua_sim/templates/OPCUANodeSet.xml",
    ),
)
