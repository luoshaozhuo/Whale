"""Shared helpers for e2e tests — importable utilities and constants."""

from __future__ import annotations

import socket
import time
from contextlib import closing
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SRC_ROOT = PROJECT_ROOT / "src"
DEFAULT_NODESET_PATH = PROJECT_ROOT / "tools" / "opcua_sim" / "templates" / "OPCUANodeSet.xml"
DEFAULT_CONNECTIONS_PATH = (
    PROJECT_ROOT / "tools" / "opcua_sim" / "templates" / "OPCUA_client_connections.yaml"
)

# Infrastructure constants (match docker-compose.ingest-dev.yaml)
PG_HOST = "127.0.0.1"
PG_PORT = 5432
PG_DB = "whale_ingest"
PG_USER = "whale"
PG_PASSWORD = "whale"

REDIS_HOST = "127.0.0.1"
REDIS_PORT = 16379

KAFKA_BOOTSTRAP_SERVER = "127.0.0.1:9092"


def get_free_port() -> int:
    """Return one currently available local TCP port."""
    with closing(socket.socket(socket.AF_INET, socket.SOCK_STREAM)) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def ensure_src_on_path() -> None:
    """Add src/ to sys.path so whale.* imports resolve."""
    import sys

    if str(SRC_ROOT) not in sys.path:
        sys.path.insert(0, str(SRC_ROOT))


def seed_postgres_for_e2e(
    pg_session,
    *,
    substation_name: str | None = None,
    model_id: str | None = None,
    model_version: str = "v1",
    variable_keys: tuple[str, ...] = ("TotW", "Spd", "WS"),
    device_code: str = "WTG_01",
    endpoint: str | None = None,
    acquisition_mode: str = "ONCE",
) -> tuple[int, int]:
    """Seed PostgreSQL with sample acquisition data. Returns (task_id, model_pk).

    substation_name/model_id default to unique-per-call values to avoid cross-test
    collisions. device_code must match the OPC UA BrowseName — keep it fixed.
    """
    import uuid as _uuid

    _suffix = _uuid.uuid4().hex[:6]
    substation_name = substation_name or f"DEMO_SUBSTATION_{_suffix}"
    model_id = model_id or f"goldwind_gw121_opcua_{_suffix}"
    from whale.ingest.framework.persistence.orm.acquisition_model_orm import (
        AcquisitionModelORM,
    )
    from whale.ingest.framework.persistence.orm.acquisition_task_orm import (
        AcquisitionTaskORM,
    )
    from whale.ingest.framework.persistence.orm.acquisition_variable_orm import (
        AcquisitionVariableORM,
    )

    # device_id is a plain integer since DeviceORM was removed
    device_id = hash(device_code) % (10**9)

    model = AcquisitionModelORM(model_id=model_id, model_version=model_version)
    pg_session.add(model)
    pg_session.flush()

    for key in variable_keys:
        pg_session.add(
            AcquisitionVariableORM(
                model_id=int(model.id),
                variable_key=key,
                locator=f"s={{device_code}}.{key}",
                locator_type="node_path",
                display_name=key,
                variable_params={},
            )
        )
    pg_session.flush()

    host, port = "127.0.0.1", None
    if endpoint:
        from urllib.parse import urlsplit

        parsed = urlsplit(endpoint)
        host = parsed.hostname or "127.0.0.1"
        port = parsed.port

    task = AcquisitionTaskORM(
        device_id=device_id,
        model_id=model_id,
        model_version=model_version,
        protocol="opcua",
        acquisition_mode=acquisition_mode,
        interval_ms=100,
        host=host,
        port=port,
        connection_params={
            "security_policy": "None",
            "security_mode": "None",
            "namespace_uri": "urn:windfarm:2wtg",
        },
        enabled=True,
    )
    pg_session.add(task)
    pg_session.flush()
    pg_session.commit()

    return int(task.id), int(model.id)


def wait_for_redis(redis_client, timeout_seconds: float = 20.0) -> None:
    """Wait until Redis responds to ping or raise actionable error."""
    import pytest

    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        try:
            if redis_client.ping():
                return
        except Exception:
            time.sleep(0.5)
            continue
        time.sleep(0.2)
    pytest.fail(
        f"Redis backend is not ready at {REDIS_HOST}:{REDIS_PORT}. "
        "Run `docker compose -f docker-compose.ingest-dev.yaml up -d` first."
    )


def wait_for_kafka(timeout_seconds: float = 30.0) -> None:
    """Wait until Kafka metadata is queryable or raise actionable error."""
    import pytest

    try:
        from kafka import KafkaConsumer  # type: ignore[import-not-found]
    except ImportError as exc:
        raise RuntimeError("E2E test requires `kafka-python` package.") from exc

    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        consumer = None
        try:
            consumer = KafkaConsumer(
                bootstrap_servers=[KAFKA_BOOTSTRAP_SERVER],
                consumer_timeout_ms=1000,
                api_version_auto_timeout_ms=2000,
            )
            consumer.topics()
            return
        except Exception:
            time.sleep(0.5)
        finally:
            if consumer is not None:
                consumer.close()
    pytest.fail(
        f"Kafka backend is not ready at {KAFKA_BOOTSTRAP_SERVER}. "
        "Run `docker compose -f docker-compose.ingest-dev.yaml up -d` first."
    )
