"""E2E test: read OPC UA states and publish one snapshot into Kafka pipeline."""

from __future__ import annotations

import asyncio
import json
import os
import socket
import time
import uuid
from contextlib import closing
from typing import Any, Protocol, cast

import pytest

from tools.opcua_sim.models import OpcUaServerConfig
from tools.opcua_sim.server_runtime import OpcUaServerRuntime
from whale.ingest.adapters.message.kafka_message_publisher import KafkaMessagePublisher
from whale.ingest.adapters.source.opcua_source_acquisition_adapter import (
    OpcUaSourceAcquisitionAdapter,
)
from whale.ingest.adapters.source.static_source_acquisition_port_registry import (
    StaticSourceAcquisitionPortRegistry,
)
from whale.ingest.adapters.state.redis_source_state_cache import (
    RedisSourceStateCache,
    RedisSourceStateCacheSettings,
)
from whale.ingest.config import KafkaMessageConfig
from whale.ingest.usecases.dtos.acquisition_item_data import AcquisitionItemData
from whale.ingest.usecases.dtos.acquisition_status import AcquisitionStatus
from whale.ingest.usecases.dtos.source_acquisition_definition import (
    SourceAcquisitionDefinition,
)
from whale.ingest.usecases.dtos.source_connection_data import SourceConnectionData
from whale.ingest.usecases.dtos.source_runtime_config_data import (
    SourceRuntimeConfigData,
)
from whale.ingest.usecases.emit_state_snapshot_usecase import EmitStateSnapshotUseCase
from whale.ingest.usecases.pull_source_state_usecase import PullSourceStateUseCase

REDIS_HOST = os.environ.get("WHALE_INGEST_REDIS_HOST", "127.0.0.1")
REDIS_PORT = int(os.environ.get("WHALE_INGEST_REDIS_PORT", "6379"))
REDIS_DB = int(os.environ.get("WHALE_INGEST_REDIS_DB", "0"))
KAFKA_BOOTSTRAP_SERVER = (
    os.environ.get("WHALE_INGEST_KAFKA_BOOTSTRAP_SERVERS", "127.0.0.1:9092").split(",")[0].strip()
)


class _RedisVerificationClient(Protocol):
    """Minimal Redis operations needed by this e2e test."""

    def ping(self) -> bool:
        """Check whether Redis connection is alive."""

    def delete(self, name: str) -> int:
        """Delete one Redis key."""

    def hgetall(self, name: str) -> dict[str, str]:
        """Read all hash fields for one key."""


class _StaticSourceAcquisitionDefinitionPort:
    """Return one static acquisition definition for the runtime config."""

    def __init__(self, definition: SourceAcquisitionDefinition) -> None:
        """Store the static definition for later reads."""
        self._definition = definition

    def get_config(self, runtime_config: SourceRuntimeConfigData) -> SourceAcquisitionDefinition:
        """Return the same definition for the provided runtime config."""
        del runtime_config
        return self._definition


def _get_free_port() -> int:
    """Return one currently available local TCP port."""
    with closing(socket.socket(socket.AF_INET, socket.SOCK_STREAM)) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _build_runtime_config() -> SourceRuntimeConfigData:
    """Build one ONCE runtime config used by this e2e case."""
    return SourceRuntimeConfigData(
        runtime_config_id=101,
        source_id="WTG_01",
        protocol="opcua",
        acquisition_mode="ONCE",
        interval_ms=0,
        enabled=True,
    )


def _build_definition(endpoint: str) -> SourceAcquisitionDefinition:
    """Build one acquisition definition for the OPC UA simulator."""
    return SourceAcquisitionDefinition(
        model_id="goldwind_gw121_opcua",
        connection=SourceConnectionData(
            endpoint=endpoint,
            params={
                "security_policy": "None",
                "security_mode": "None",
                "namespace_uri": "urn:windfarm:2wtg",
            },
        ),
        items=[
            AcquisitionItemData(key="TotW", locator="s=WTG_01.TotW", display_name="TotW"),
            AcquisitionItemData(key="Spd", locator="s=WTG_01.Spd", display_name="Spd"),
            AcquisitionItemData(key="WS", locator="s=WTG_01.WS", display_name="WS"),
        ],
    )


def _build_redis_client() -> _RedisVerificationClient:
    """Build one real Redis client for e2e verification and cleanup."""
    try:
        from redis import Redis
    except ImportError as exc:
        raise RuntimeError("E2E test requires `redis` package.") from exc
    return cast(
        _RedisVerificationClient,
        Redis(host=REDIS_HOST, port=REDIS_PORT, db=REDIS_DB, decode_responses=True),
    )


def _wait_for_redis(redis_client: _RedisVerificationClient, timeout_seconds: float = 20.0) -> None:
    """Wait until Redis responds to ping or fail with actionable message."""
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
        "Redis backend is not ready at "
        f"{REDIS_HOST}:{REDIS_PORT}. Run `sg docker -c 'bash scripts/run_ingest_dev.sh'` first."
    )


def _wait_for_kafka(timeout_seconds: float = 30.0) -> None:
    """Wait until Kafka metadata is queryable or fail with actionable message."""
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
        "Kafka backend is not ready at "
        f"{KAFKA_BOOTSTRAP_SERVER}. Run `sg docker -c 'bash scripts/run_ingest_dev.sh'` first."
    )


def _consume_one_snapshot_message(topic: str, timeout_seconds: float = 20.0) -> dict[str, Any]:
    """Consume one published snapshot from Kafka topic and return JSON payload."""
    try:
        from kafka import KafkaConsumer  # type: ignore[import-not-found]
    except ImportError as exc:
        raise RuntimeError("E2E test requires `kafka-python` package.") from exc

    consumer = KafkaConsumer(
        topic,
        bootstrap_servers=[KAFKA_BOOTSTRAP_SERVER],
        auto_offset_reset="earliest",
        enable_auto_commit=False,
        group_id=f"whale-e2e-{uuid.uuid4().hex}",
        consumer_timeout_ms=1000,
        value_deserializer=lambda raw: json.loads(raw.decode("utf-8")),
    )
    deadline = time.monotonic() + timeout_seconds
    try:
        while time.monotonic() < deadline:
            polled = consumer.poll(timeout_ms=1000, max_records=10)
            for records in polled.values():
                for record in records:
                    value = record.value
                    if isinstance(value, dict):
                        return value
        pytest.fail(f"No snapshot message consumed from Kafka topic: {topic}")
    finally:
        consumer.close()

    raise AssertionError("Unreachable")


@pytest.mark.e2e
def test_e2e_reads_opcua_and_publishes_snapshot_to_kafka_pipeline() -> None:
    """Run one end-to-end flow with real Redis and Kafka backends."""
    endpoint = f"opc.tcp://127.0.0.1:{_get_free_port()}"
    runtime_config = _build_runtime_config()
    definition = _build_definition(endpoint)
    station_id = f"station-e2e-{uuid.uuid4().hex[:8]}"
    hash_key = f"whale:ingest:state:e2e:{uuid.uuid4().hex}"
    topic = f"whale.ingest.state_snapshot.v1.e2e.{uuid.uuid4().hex}"

    redis_client = _build_redis_client()
    _wait_for_redis(redis_client)
    _wait_for_kafka()
    redis_client.delete(hash_key)

    state_cache = RedisSourceStateCache(
        settings=RedisSourceStateCacheSettings(
            host=REDIS_HOST,
            port=REDIS_PORT,
            db=REDIS_DB,
            username=None,
            password=None,
            hash_key=hash_key,
            station_id=station_id,
            decode_responses=True,
        ),
        client=redis_client,
    )

    message_publisher = KafkaMessagePublisher(
        settings=KafkaMessageConfig(
            bootstrap_servers=(KAFKA_BOOTSTRAP_SERVER,),
            topic=topic,
            ack_timeout_seconds=10.0,
        ),
    )

    emit_use_case = EmitStateSnapshotUseCase(
        snapshot_reader_port=state_cache,
        publisher=message_publisher,
    )

    pull_use_case = PullSourceStateUseCase(
        acquisition_definition_port=_StaticSourceAcquisitionDefinitionPort(definition),
        acquisition_port_registry=StaticSourceAcquisitionPortRegistry(
            {"opcua": OpcUaSourceAcquisitionAdapter()}
        ),
        state_cache_port=state_cache,
        snapshot_emitter=emit_use_case,
    )

    with OpcUaServerRuntime(
        nodeset_path="tools/opcua_sim/templates/OPCUANodeSet.xml",
        config=OpcUaServerConfig(
            name="WTG_01",
            endpoint=endpoint,
            security_policy="None",
            security_mode="None",
            update_interval_seconds=0.1,
        ),
    ):
        result = asyncio.run(pull_use_case.execute([runtime_config]))[0]

    try:
        assert result.status is AcquisitionStatus.SUCCEEDED

        redis_rows = redis_client.hgetall(hash_key)
        assert len(redis_rows) >= 3

        message = _consume_one_snapshot_message(topic)
        assert message["message_type"] == "STATE_SNAPSHOT"
        assert message["source_module"] == "ingest"
        assert message["item_count"] >= 3
        assert {item["variable_key"] for item in message["items"]} >= {"TotW", "Spd", "WS"}
    finally:
        redis_client.delete(hash_key)
