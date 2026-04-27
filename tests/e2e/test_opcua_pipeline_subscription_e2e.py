"""E2E test: OPC UA subscription continuously updates Redis and publishes Kafka snapshots."""

from __future__ import annotations

import asyncio
import json
import os
import time
import uuid
from threading import Event
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
from whale.ingest.usecases.subscribe_source_state_usecase import (  # noqa: E402
    SubscribeSourceStateUseCase,
)

REDIS_DB = int(os.environ.get("WHALE_INGEST_REDIS_DB", "0"))


def _consume_messages_from_beginning(
    topic: str, timeout_seconds: float = 10.0, min_messages: int = 2
) -> list[dict[str, Any]]:
    """Consume at least `min_messages` snapshot messages from Kafka."""
    try:
        from kafka import KafkaConsumer  # type: ignore[import-not-found]
    except ImportError as exc:
        raise RuntimeError("E2E test requires `kafka-python` package.") from exc

    consumer = KafkaConsumer(
        topic,
        bootstrap_servers=[KAFKA_BOOTSTRAP_SERVER],
        auto_offset_reset="earliest",
        enable_auto_commit=False,
        group_id=f"whale-e2e-sub-{uuid.uuid4().hex}",
        consumer_timeout_ms=1000,
        value_deserializer=lambda raw: json.loads(raw.decode("utf-8")),
    )
    messages: list[dict[str, Any]] = []
    deadline = time.monotonic() + timeout_seconds
    try:
        while time.monotonic() < deadline and len(messages) < min_messages:
            polled = consumer.poll(timeout_ms=1000, max_records=10)
            for records in polled.values():
                for record in records:
                    value = record.value
                    if isinstance(value, dict):
                        messages.append(value)
    finally:
        consumer.close()
    return messages


@pytest.mark.e2e
def test_e2e_subscription_updates_redis_and_publishes_to_kafka(
    pg_session,
    session_factory,
    redis_client,
    _kafka_ready,
) -> None:
    """Start an OPC UA subscription, verify Redis values change and Kafka snapshots appear."""
    endpoint = f"opc.tcp://127.0.0.1:{get_free_port()}"

    # --- Seed PostgreSQL with SUBSCRIPTION-mode task ---
    task_id, _ = seed_postgres_for_e2e(
        pg_session,
        endpoint=endpoint,
        acquisition_mode="SUBSCRIPTION",
    )

    hash_key = f"whale:ingest:state:e2e-sub:{uuid.uuid4().hex}"
    topic = f"whale.ingest.state_snapshot.v1.e2e.sub.{uuid.uuid4().hex}"
    station_id = f"station-e2e-sub-{uuid.uuid4().hex[:8]}"

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

    definition_repo = OpcUaSourceAcquisitionDefinitionRepository(
        session_factory=session_factory,
    )
    runtime_repo = SourceRuntimeConfigRepository(session_factory=session_factory)

    subscribe_use_case = SubscribeSourceStateUseCase(
        acquisition_definition_port=definition_repo,
        acquisition_port_registry=StaticSourceAcquisitionPortRegistry(
            {"opcua": OpcUaSourceAcquisitionAdapter()}
        ),
        state_cache_port=state_cache,
        snapshot_emitter=emit_use_case,
    )

    runtime_configs = runtime_repo.list_enabled()
    assert len(runtime_configs) >= 1, "Expected at least one enabled runtime config"

    # --- Run subscription in background, OPC UA server provides live values ---
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
        time.sleep(0.5)  # let OPC UA server bind its socket
        stop_event = Event()

        async def _subscribe():
            await subscribe_use_case.execute(
                runtime_configs=tuple(runtime_configs),
                stop_event=stop_event,
            )

        import threading as _threading

        def _run_in_thread():
            asyncio.run(_subscribe())

        t = _threading.Thread(target=_run_in_thread, daemon=True)
        t.start()

        # Let subscription run and accumulate data (~8 seconds)
        time.sleep(8.0)
        stop_event.set()
        t.join(timeout=5.0)

    try:
        # --- Assertions ---
        redis_rows = redis_client.hgetall(hash_key)
        assert len(redis_rows) >= 3, (
            f"Expected >= 3 Redis hash entries, got {len(redis_rows)}: {redis_rows}"
        )

        messages = _consume_messages_from_beginning(topic, min_messages=1)
        assert len(messages) >= 1, (
            f"Expected >= 1 Kafka snapshot messages from subscription, got {len(messages)}"
        )
        for msg in messages:
            assert msg["message_type"] == "STATE_SNAPSHOT"
            assert msg["source_module"] == "ingest"
            assert msg["item_count"] >= 3
    finally:
        redis_client.delete(hash_key)
