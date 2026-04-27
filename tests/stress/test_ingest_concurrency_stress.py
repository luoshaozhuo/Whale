"""Stress tests: many GB/T 30966.2 fields, multiple OPC UA turbines, concurrent reads."""

from __future__ import annotations

import asyncio
import json
import os
import time
import uuid
from pathlib import Path
from threading import Event
from typing import Any

import pytest

from tests.e2e.helpers import (
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
from tools.opcua_sim.templates.gbt_30966_fields import build_field_dict, total_field_count

ensure_src_on_path()

from tools.opcua_sim.generate_nodeset import generate_nodeset_xml  # noqa: E402
from tools.opcua_sim.templates.gbt_30966_fields import ALL_LOGICAL_NODES  # noqa: E402
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
TMP_DIR = Path(__file__).resolve().parents[2] / "tests" / "tmp"
TMP_DIR.mkdir(exist_ok=True)


# ==============================================================================
# Helpers
# ==============================================================================


def _seed_stress_data(pg_session, endpoints: list[str]) -> list[int]:
    """Seed PostgreSQL with stress test data using full GB/T fields. Returns task_ids."""
    field_keys = tuple(build_field_dict().keys())
    task_ids = []
    for i, endpoint in enumerate(endpoints):
        tid, _ = seed_postgres_for_e2e(
            pg_session,
            endpoint=endpoint,
            device_code=f"WTG_{i+1:02d}",
            variable_keys=field_keys,
            acquisition_mode="ONCE",
        )
        task_ids.append(tid)
    return task_ids


# ==============================================================================
# Stress Tests
# ==============================================================================


@pytest.mark.stress
@pytest.mark.slow
def test_stress_many_fields_single_pull(
    pg_session,
    session_factory,
    redis_client,
    _kafka_ready,
) -> None:
    """Pull all ~500 GB/T fields from one OPC UA turbine. Measure throughput."""
    endpoint = f"opc.tcp://127.0.0.1:{get_free_port()}"
    field_count = total_field_count()
    variable_values = build_field_dict()

    _seed_stress_data(pg_session, [endpoint])

    # Generate large NodeSet
    nodeset_xml = generate_nodeset_xml(turbine_count=1)
    nodeset_path = TMP_DIR / "stress_nodeset_1wtg.xml"
    nodeset_path.write_text(nodeset_xml, encoding="utf-8")

    hash_key = f"whale:ingest:state:stress:{uuid.uuid4().hex}"
    topic = f"whale.ingest.state_snapshot.v1.stress.{uuid.uuid4().hex}"
    station_id = f"station-stress-{uuid.uuid4().hex[:8]}"

    wait_for_redis(redis_client)
    wait_for_kafka()
    redis_client.delete(hash_key)

    state_cache = RedisSourceStateCache(
        settings=RedisSourceStateCacheSettings(
            host=REDIS_HOST, port=REDIS_PORT, db=REDIS_DB,
            username=None, password=None,
            hash_key=hash_key, station_id=station_id, decode_responses=True,
        ),
        client=redis_client,
    )

    message_publisher = KafkaMessagePublisher(
        settings=KafkaMessageConfig(
            bootstrap_servers=(KAFKA_BOOTSTRAP_SERVER,),
            topic=topic, ack_timeout_seconds=30.0,
        ),
    )

    emit_use_case = EmitStateSnapshotUseCase(
        snapshot_reader_port=state_cache, publisher=message_publisher,
    )

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
        max_in_flight=1,
    )

    runtime_configs = runtime_repo.list_enabled()
    assert len(runtime_configs) >= 1, "Expected at least 1 enabled runtime config"

    with OpcUaServerRuntime(
        nodeset_path=str(nodeset_path),
        config=OpcUaServerConfig(
            name="WTG_01", endpoint=endpoint,
            security_policy="None", security_mode="None",
            update_interval_seconds=0.1,
        ),
        variable_values=variable_values,
    ):
        time.sleep(1.5)  # let large NodeSet server start
        t0 = time.monotonic()
        results = asyncio.run(pull_use_case.execute(runtime_configs))
        elapsed = time.monotonic() - t0

    try:
        succeeded = sum(1 for r in results if r.status.name == "SUCCEEDED")
        total_states = sum(r.total_states for r in results)

        print(f"\n{'='*60}")
        print(f"  STRESS: {field_count} fields, 1 turbine, ONCE pull")
        print(f"  Elapsed:   {elapsed:.2f}s")
        print(f"  Succeeded: {succeeded}/{len(results)} tasks")
        print(f"  States:    {total_states}")
        print(f"  Rate:      {total_states / elapsed:.1f} states/s")
        print(f"{'='*60}\n")

        assert succeeded >= 1, f"No successful pulls out of {len(results)}"
        assert total_states >= field_count * 0.9, (
            f"Expected >= {field_count * 0.9:.0f} states, got {total_states}"
        )

        redis_rows = redis_client.hgetall(hash_key)
        assert len(redis_rows) >= field_count * 0.8, (
            f"Expected >= {field_count * 0.8:.0f} Redis entries, got {len(redis_rows)}"
        )
    finally:
        redis_client.delete(hash_key)
        if nodeset_path.exists():
            nodeset_path.unlink()


@pytest.mark.stress
@pytest.mark.slow
def test_stress_multiple_turbines_concurrent_read(
    pg_session,
    session_factory,
    redis_client,
    _kafka_ready,
) -> None:
    """Pull ~500 fields from 3 turbines concurrently. Measure concurrency capacity."""
    turbine_count = 3
    endpoints = [f"opc.tcp://127.0.0.1:{get_free_port()}" for _ in range(turbine_count)]
    field_count = total_field_count()
    variable_values = build_field_dict()

    _seed_stress_data(pg_session, endpoints)

    nodeset_xml = generate_nodeset_xml(turbine_count=turbine_count)
    nodeset_path = TMP_DIR / "stress_nodeset_3wtg.xml"
    nodeset_path.write_text(nodeset_xml, encoding="utf-8")

    hash_key = f"whale:ingest:state:stress-multi:{uuid.uuid4().hex}"
    topic = f"whale.ingest.state_snapshot.v1.stress.multi.{uuid.uuid4().hex}"
    station_id = f"station-stress-multi-{uuid.uuid4().hex[:8]}"

    wait_for_redis(redis_client)
    wait_for_kafka()
    redis_client.delete(hash_key)

    state_cache = RedisSourceStateCache(
        settings=RedisSourceStateCacheSettings(
            host=REDIS_HOST, port=REDIS_PORT, db=REDIS_DB,
            username=None, password=None,
            hash_key=hash_key, station_id=station_id, decode_responses=True,
        ),
        client=redis_client,
    )

    message_publisher = KafkaMessagePublisher(
        settings=KafkaMessageConfig(
            bootstrap_servers=(KAFKA_BOOTSTRAP_SERVER,),
            topic=topic, ack_timeout_seconds=30.0,
        ),
    )

    emit_use_case = EmitStateSnapshotUseCase(
        snapshot_reader_port=state_cache, publisher=message_publisher,
    )

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
        max_in_flight=8,
    )

    runtime_configs = runtime_repo.list_enabled()
    assert len(runtime_configs) >= turbine_count

    servers = []
    for i, endpoint in enumerate(endpoints):
        server = OpcUaServerRuntime(
            nodeset_path=str(nodeset_path),
            config=OpcUaServerConfig(
                name=f"WTG_{i+1:02d}", endpoint=endpoint,
                security_policy="None", security_mode="None",
                update_interval_seconds=0.1,
            ),
            variable_values=variable_values,
        )
        server.start()
        servers.append(server)

    try:
        time.sleep(2.0)  # let all servers start
        t0 = time.monotonic()
        results = asyncio.run(pull_use_case.execute(runtime_configs))
        elapsed = time.monotonic() - t0
    finally:
        for server in servers:
            server.stop()

    try:
        succeeded = sum(1 for r in results if r.status.name == "SUCCEEDED")
        total_states = sum(r.total_states for r in results)
        expected_min = field_count * turbine_count * 0.8

        print(f"\n{'='*60}")
        print(f"  STRESS: {field_count} fields x {turbine_count} turbines, ONCE pull")
        print(f"  Elapsed:   {elapsed:.2f}s")
        print(f"  Succeeded: {succeeded}/{len(results)} tasks")
        print(f"  States:    {total_states} (expected >= {expected_min:.0f})")
        print(f"  Rate:      {total_states / elapsed:.1f} states/s")
        print(f"{'='*60}\n")

        assert succeeded >= turbine_count, f"Only {succeeded}/{turbine_count} tasks succeeded"
        assert total_states >= expected_min, (
            f"Expected >= {expected_min:.0f} states, got {total_states}"
        )
    finally:
        redis_client.delete(hash_key)
        if nodeset_path.exists():
            nodeset_path.unlink()
