"""E2E: OPC UA servers from shared DB → ingest pipeline → Redis + Kafka."""

from __future__ import annotations

import asyncio
import json as _json
import time
import uuid

import pytest

from tests.e2e.helpers import ensure_src_on_path

ensure_src_on_path()


@pytest.mark.e2e
def test_e2e_db_driven_pipeline_reads_wtg_and_publishes_to_kafka(
    pg_session, _kafka_ready, redis_client, session_factory,
) -> None:
    """E2E: OPC UA servers from shared DB, full pipeline → Redis + Kafka."""
    from whale.shared.persistence.session import session_scope
    from sqlalchemy import text

    # ── 1. Query shared DB for keys and turbine config ──────────────
    with session_scope() as s:
        from sqlalchemy import select
        from whale.shared.persistence.orm import (
            AcquisitionTask, CommunicationEndpoint,
            LDInstance, SignalProfileItem,
        )

        task = s.scalars(
            select(AcquisitionTask).where(AcquisitionTask.task_name == "task_ZB-WTG-001")
        ).first()
        assert task is not None, "AcquisitionTask 'task_ZB-WTG-001' not found"

        ld = s.get(LDInstance, task.ld_instance_id)
        assert ld is not None, f"LDInstance {task.ld_instance_id} not found"

        ep = s.get(CommunicationEndpoint, ld.endpoint_id)
        assert ep is not None, f"CommunicationEndpoint {ld.endpoint_id} not found"
        endpoint = f"opc.tcp://{ep.host}:{ep.port}" if ep.host and ep.port else ""

        keys = s.scalars(
            select(SignalProfileItem.do_name)
            .where(SignalProfileItem.signal_profile_id == ld.signal_profile_id)
            .order_by(SignalProfileItem.sort_order)
        ).all()
        all_keys = tuple(keys)
        print(f"WTG variable keys from DB: {len(all_keys)}")

    # ── 2. Seed ingest DB ──────────────────────────────────────────
    from tests.e2e.helpers import seed_postgres_for_e2e
    task_id, model_pk = seed_postgres_for_e2e(
        pg_session,
        device_code="ZB-WTG-001",
        endpoint=endpoint,
        acquisition_mode="ONCE",
        variable_keys=all_keys[:50],
    )

    # ── 3. Kill lingering OPC UA processes, then start fleet ────────
    import subprocess as _sp
    try:
        out = _sp.check_output(["ss", "-tlnp"], text=True, timeout=5)
        for line in out.split("\n"):
            for port in range(40001, 40033):
                if f":{port}" in line and "pid=" in line:
                    pid = line.split("pid=")[-1].split(",")[0].strip()
                    if pid.isdigit():
                        _sp.run(["kill", "-9", pid], capture_output=True)
    except Exception:
        pass

    from tools.source_simulation.opcua_sim.fleet_runtime import OpcUaFleetRuntime
    fleet = OpcUaFleetRuntime.from_database()
    runtime = fleet._runtimes[0]
    runtime.start()
    time.sleep(1.5)
    print(f"Server started: {runtime.name} at {runtime.endpoint}")

    # ── 4. Build pipeline and pull ──────────────────────────────────
    from whale.ingest.adapters.message.kafka_message_publisher import \
        KafkaMessagePublisher
    from whale.ingest.adapters.source.opcua_source_acquisition_adapter import \
        OpcUaSourceAcquisitionAdapter
    from whale.ingest.adapters.state.redis_source_state_cache import \
        RedisSourceStateCache, RedisSourceStateCacheSettings
    from whale.ingest.usecases.emit_state_snapshot_usecase import \
        EmitStateSnapshotUseCase
    from whale.ingest.usecases.execute_source_acquisition_usecase import \
        ExecuteSourceAcquisitionUseCase
    from whale.ingest.adapters.config.source_runtime_config_repository import \
        SourceRuntimeConfigRepository
    from whale.ingest.adapters.config.opcua_source_acquisition_definition_repository import \
        OpcUaSourceAcquisitionDefinitionRepository
    from whale.ingest.adapters.source.static_source_acquisition_port_registry import \
        StaticSourceAcquisitionPortRegistry
    from whale.ingest.config import KafkaMessageConfig

    station_id = f"ZB-E2E-{uuid.uuid4().hex[:6]}"
    topic = f"whale.ingest.e2e.{uuid.uuid4().hex[:6]}"
    hash_key = f"whale:e2e:{uuid.uuid4().hex[:6]}"

    try:
        state_cache = RedisSourceStateCache(
            settings=RedisSourceStateCacheSettings(
                host="127.0.0.1", port=16379, db=0,
                hash_key=hash_key, station_id=station_id,
            ),
            client=redis_client,
        )
        publisher = KafkaMessagePublisher(
            settings=KafkaMessageConfig(
                bootstrap_servers=("127.0.0.1:9092",), topic=topic,
                ack_timeout_seconds=30.0,
            )
        )
        emit_uc = EmitStateSnapshotUseCase(
            snapshot_reader_port=state_cache,
            publisher=publisher,
        )
        def_repo = OpcUaSourceAcquisitionDefinitionRepository(session_factory)
        config_repo = SourceRuntimeConfigRepository(session_factory)
        registry = StaticSourceAcquisitionPortRegistry(
            {"opcua": OpcUaSourceAcquisitionAdapter(),
             "OPC_UA": OpcUaSourceAcquisitionAdapter()}
        )
        pull_uc = ExecuteSourceAcquisitionUseCase(
            acquisition_port_registry=registry,
            state_cache_port=state_cache,
        )

        async def _pull():
            return await pull_uc.execute(config_repo.list_enabled())
        results = asyncio.run(_pull())
        assert isinstance(results, list) and len(results) > 0, f"Pull failed: {results}"

        emit_result = emit_uc.execute()

        cached = redis_client.hgetall(hash_key)
        print(f"Redis: {len(cached)} entries")
        assert len(cached) >= 10, f"Redis: {len(cached)} (expected 10+)"

        # Consume Kafka
        from kafka import KafkaConsumer
        consumer = KafkaConsumer(
            topic, bootstrap_servers="127.0.0.1:9092",
            auto_offset_reset="earliest", consumer_timeout_ms=10000,
            group_id=f"e2e-{uuid.uuid4().hex[:6]}", max_poll_records=5,
        )
        msg = None
        try:
            for m in consumer:
                try:
                    body = _json.loads(m.value.decode("utf-8"))
                    if body.get("message_type") == "STATE_SNAPSHOT":
                        msg = body; break
                except Exception:
                    pass
        finally:
            consumer.close()
        assert msg is not None, "No Kafka STATE_SNAPSHOT message"

    finally:
        redis_client.delete(hash_key)
        runtime.stop()
        fleet._temp_dir.cleanup() if fleet._temp_dir else None
