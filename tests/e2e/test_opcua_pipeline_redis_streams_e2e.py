"""E2E test: OPC UA pull publishes snapshots into Redis Streams — full PostgreSQL + Redis backend."""

from __future__ import annotations

import asyncio
import json
import os
import uuid

import pytest

from tests.e2e.helpers import (
    DEFAULT_NODESET_PATH,
    REDIS_HOST,
    REDIS_PORT,
    ensure_src_on_path,
    get_free_port,
    seed_postgres_for_e2e,
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
from whale.ingest.adapters.message.redis_streams_message_publisher import (  # noqa: E402
    RedisStreamsMessagePublisher,
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
from whale.ingest.config import RedisStreamsMessageConfig  # noqa: E402
from whale.ingest.usecases.emit_state_snapshot_usecase import (  # noqa: E402
    EmitStateSnapshotUseCase,
)
from whale.ingest.usecases.pull_source_state_usecase import (  # noqa: E402
    PullSourceStateUseCase,
)

REDIS_DB = int(os.environ.get("WHALE_INGEST_REDIS_DB", "0"))


def _read_stream_messages(
    stream_key: str, count: int = 10
) -> list[dict[str, str]]:
    """Read recent messages from a Redis stream."""
    try:
        from redis import Redis
    except ImportError as exc:
        raise RuntimeError("E2E test requires `redis` package.") from exc

    client = Redis(host=REDIS_HOST, port=REDIS_PORT, db=REDIS_DB, decode_responses=True)
    try:
        result = client.xread({stream_key: "0"}, count=count)
        messages: list[dict[str, str]] = []
        for _stream, entries in result:
            for _entry_id, fields in entries:
                if "message" in fields:
                    messages.append(json.loads(fields["message"]))
        return messages
    finally:
        client.close()


@pytest.mark.e2e
def test_e2e_reads_opcua_and_publishes_snapshot_to_redis_streams(
    pg_session,
    session_factory,
    redis_client,
) -> None:
    """Run one end-to-end flow with real PostgreSQL and Redis Streams message backend."""
    endpoint = f"opc.tcp://127.0.0.1:{get_free_port()}"

    # --- Seed PostgreSQL ---
    task_id, _ = seed_postgres_for_e2e(
        pg_session,
        endpoint=endpoint,
        acquisition_mode="ONCE",
    )

    hash_key = f"whale:ingest:state:e2e-rs:{uuid.uuid4().hex}"
    stream_key = f"whale:ingest:state_snapshot:v1:e2e-rs:{uuid.uuid4().hex}"
    station_id = f"station-e2e-rs-{uuid.uuid4().hex[:8]}"
    redis_url = f"redis://{REDIS_HOST}:{REDIS_PORT}/{REDIS_DB}"

    wait_for_redis(redis_client)
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

    message_publisher = RedisStreamsMessagePublisher(
        settings=RedisStreamsMessageConfig(
            redis_url=redis_url,
            stream_key=stream_key,
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

    pull_use_case = PullSourceStateUseCase(
        acquisition_definition_port=definition_repo,
        acquisition_port_registry=StaticSourceAcquisitionPortRegistry(
            {"opcua": OpcUaSourceAcquisitionAdapter()}
        ),
        state_cache_port=state_cache,
        snapshot_emitter=emit_use_case,
    )

    runtime_configs = runtime_repo.list_enabled()
    assert len(runtime_configs) >= 1

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
        result = asyncio.run(pull_use_case.execute(runtime_configs))[0]

    try:
        assert result.status.name == "SUCCEEDED"

        redis_rows = redis_client.hgetall(hash_key)
        assert len(redis_rows) >= 3

        messages = _read_stream_messages(stream_key, count=5)
        assert len(messages) >= 1, "Expected at least 1 snapshot message in Redis stream"
        msg = messages[0]
        assert msg["message_type"] == "STATE_SNAPSHOT"
        assert msg["source_module"] == "ingest"
        assert msg["item_count"] >= 3
    finally:
        redis_client.delete(hash_key)
