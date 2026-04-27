"""E2E test: read OPC UA states and publish one snapshot into Kafka — full PostgreSQL + Redis + Kafka."""

from __future__ import annotations

import asyncio
import json
import os
import uuid
from typing import Any

import pytest

from tests.e2e.helpers import (
    DEFAULT_NODESET_PATH,
    KAFKA_BOOTSTRAP_SERVER,
    REDIS_HOST,
    REDIS_PORT,
    ensure_src_on_path,
    get_free_port,
    seed_postgres_for_e2e,
    wait_for_kafka,
    wait_for_redis,
)
from tools.opcua_sim.models import OpcUaServerConfig
from tools.opcua_sim.server_runtime import OpcUaServerRuntime

ensure_src_on_path()

from whale.ingest.adapters.config.opcua_source_acquisition_definition_repository import (  # noqa: E402
    OpcUaSourceAcquisitionDefinitionRepository,
)
from whale.ingest.adapters.config.source_runtime_config_repository import (  # noqa: E402
    SourceRuntimeConfigRepository,
)
from whale.ingest.adapters.message.kafka_message_publisher import (  # noqa: E402
    KafkaMessagePublisher,
)
from whale.ingest.adapters.source.opcua_source_acquisition_adapter import (  # noqa: E402
    OpcUaSourceAcquisitionAdapter,
)
from whale.ingest.adapters.source.static_source_acquisition_port_registry import (  # noqa: E402
    StaticSourceAcquisitionPortRegistry,
)
from whale.ingest.adapters.state.redis_source_state_cache import (  # noqa: E402
    RedisSourceStateCache,
    RedisSourceStateCacheSettings,
)
from whale.ingest.config import KafkaMessageConfig  # noqa: E402
from whale.ingest.usecases.emit_state_snapshot_usecase import (  # noqa: E402
    EmitStateSnapshotUseCase,
)
from whale.ingest.usecases.pull_source_state_usecase import (  # noqa: E402
    PullSourceStateUseCase,
)

REDIS_DB = int(os.environ.get("WHALE_INGEST_REDIS_DB", "0"))


def _consume_one_snapshot_message(topic: str, timeout_seconds: float = 20.0) -> dict[str, Any]:
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
    import time

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
def test_e2e_reads_opcua_and_publishes_snapshot_to_kafka_pipeline(
    pg_session,
    session_factory,
    redis_client,
    _kafka_ready,
) -> None:
    """Run one end-to-end flow with real PostgreSQL, Redis and Kafka backends."""
    endpoint = f"opc.tcp://127.0.0.1:{get_free_port()}"

    # --- Seed PostgreSQL ---
    task_id, model_pk = seed_postgres_for_e2e(
        pg_session,
        endpoint=endpoint,
        acquisition_mode="ONCE",
    )

    # --- Infrastructure ---
    hash_key = f"whale:ingest:state:e2e:{uuid.uuid4().hex}"
    topic = f"whale.ingest.state_snapshot.v1.e2e.{uuid.uuid4().hex}"
    station_id = f"station-e2e-{uuid.uuid4().hex[:8]}"

    wait_for_redis(redis_client)
    wait_for_kafka()
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

    # --- DB-backed repositories ---
    definition_repo = OpcUaSourceAcquisitionDefinitionRepository(
        session_factory=session_factory,
    )
    runtime_repo = SourceRuntimeConfigRepository(session_factory=session_factory)

    pull_use_case = PullSourceStateUseCase(
        acquisition_definition_port=definition_repo,
        acquisition_port_registry=StaticSourceAcquisitionPortRegistry(
            {"opcua": OpcUaSourceAcquisitionAdapter()}
        ),
        state_cache_port=state_cache,
        snapshot_emitter=emit_use_case,
    )

    # --- Run ---
    runtime_configs = runtime_repo.list_enabled()
    assert len(runtime_configs) >= 1, "Expected at least one enabled runtime config"

    with OpcUaServerRuntime(
        nodeset_path=str(DEFAULT_NODESET_PATH),
        config=OpcUaServerConfig(
            name="WTG_01",
            endpoint=endpoint,
            security_policy="None",
            security_mode="None",
            update_interval_seconds=0.1,
        ),
    ):
        import time as _time
        import socket as _socket

        # Wait until OPC UA server is actually listening
        _port = int(endpoint.rsplit(":", 1)[-1])
        _deadline = _time.monotonic() + 10.0
        while _time.monotonic() < _deadline:
            try:
                with _socket.create_connection(("127.0.0.1", _port), timeout=0.5):
                    break
            except OSError:
                _time.sleep(0.1)
        result = asyncio.run(pull_use_case.execute(runtime_configs))[0]

    try:
        assert result.status.name == "SUCCEEDED", (
            f"Pull failed: {result.status.name}, error: {result.error_message}"
        )

        # --- Redis assertions ---
        redis_rows = redis_client.hgetall(hash_key)
        assert len(redis_rows) >= 3

        # --- Kafka assertions ---
        message = _consume_one_snapshot_message(topic)
        assert message["message_type"] == "STATE_SNAPSHOT"
        assert message["source_module"] == "ingest"
        assert message["item_count"] >= 3
        assert {item["variable_key"] for item in message["items"]} >= {"TotW", "Spd", "WS"}
    finally:
        redis_client.delete(hash_key)
