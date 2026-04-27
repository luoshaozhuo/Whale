"""Ingest runtime entrypoint.

职责：
- 组装依赖
- 注册进程退出信号
- 启动 scheduler
- 退出时主动释放数据库连接池
"""

from __future__ import annotations

import signal
import sys
from threading import Event
from types import FrameType
from typing import cast

from whale.ingest.adapters.config.opcua_source_acquisition_definition_repository import (
    OpcUaSourceAcquisitionDefinitionRepository,
)
from whale.ingest.adapters.config.source_runtime_config_repository import (
    SourceRuntimeConfigRepository,
)
from whale.ingest.adapters.message.kafka_message_publisher import KafkaMessagePublisher
from whale.ingest.adapters.message.redis_streams_message_publisher import (
    RedisStreamsMessagePublisher,
)
from whale.ingest.adapters.message.relational_outbox_message_publisher import (
    RelationalOutboxMessagePublisher,
)
from whale.ingest.adapters.source.opcua_source_acquisition_adapter import (
    OpcUaSourceAcquisitionAdapter,
)
from whale.ingest.adapters.source.static_source_acquisition_port_registry import (
    StaticSourceAcquisitionPortRegistry,
)
from whale.ingest.adapters.state.redis_source_state_cache import (
    RedisSourceStateCache,
)
from whale.ingest.adapters.state.sqlite_source_state_cache import (
    SqliteSourceStateCache,
)
from whale.ingest.config import (
    CONFIG,
    KafkaMessageConfig,
    RedisStreamsMessageConfig,
    RelationalOutboxMessageConfig,
)
from whale.ingest.framework.persistence.session import dispose_engine
from whale.ingest.ports.message import MessagePublisherPort
from whale.ingest.ports.state import SourceStateCachePort, SourceStateSnapshotReaderPort
from whale.ingest.runtime.scheduler import SourceScheduler
from whale.ingest.runtime.scheduler_settings import SchedulerSettings
from whale.ingest.usecases.emit_state_snapshot_usecase import EmitStateSnapshotUseCase
from whale.ingest.usecases.pull_source_state_usecase import (
    PullSourceStateUseCase,
)
from whale.ingest.usecases.subscribe_source_state_usecase import (
    SubscribeSourceStateUseCase,
)


def build_scheduler() -> SourceScheduler:
    """构建 scheduler 及其依赖."""
    runtime_config_port = SourceRuntimeConfigRepository()
    settings = SchedulerSettings(scheduler_type="background")

    return SourceScheduler(
        runtime_config_port=runtime_config_port,
        pull_source_state_usecase_factory=lambda: _build_pull_source_state_usecase(settings),
        subscribe_source_state_usecase_factory=_build_subscribe_source_state_usecase,
        settings=settings,
    )


def _build_state_cache_port() -> SourceStateCachePort:
    """Build the configured state-cache adapter for the current environment."""
    if CONFIG.state_cache_backend == "relational":
        return SqliteSourceStateCache()
    if CONFIG.state_cache_backend == "redis":
        return RedisSourceStateCache()
    raise RuntimeError(
        "Unsupported state cache backend configured: " f"{CONFIG.state_cache_backend!r}"
    )


def _build_pull_source_state_usecase(settings: SchedulerSettings) -> PullSourceStateUseCase:
    """Build one short-lived pull use case for ONCE or POLLING jobs."""
    state_cache_port = _build_state_cache_port()
    return PullSourceStateUseCase(
        acquisition_definition_port=OpcUaSourceAcquisitionDefinitionRepository(),
        acquisition_port_registry=StaticSourceAcquisitionPortRegistry(
            {"opcua": OpcUaSourceAcquisitionAdapter()}
        ),
        state_cache_port=state_cache_port,
        snapshot_emitter=_build_emit_state_snapshot_usecase(state_cache_port),
        max_in_flight=settings.pull_max_in_flight,
    )


def _build_subscribe_source_state_usecase() -> SubscribeSourceStateUseCase:
    """Build one long-running subscription use case."""
    state_cache_port = _build_state_cache_port()
    return SubscribeSourceStateUseCase(
        acquisition_definition_port=OpcUaSourceAcquisitionDefinitionRepository(),
        acquisition_port_registry=StaticSourceAcquisitionPortRegistry(
            {"opcua": OpcUaSourceAcquisitionAdapter()}
        ),
        state_cache_port=state_cache_port,
        snapshot_emitter=_build_emit_state_snapshot_usecase(state_cache_port),
    )


def _build_emit_state_snapshot_usecase(
    state_cache_port: SourceStateCachePort,
) -> EmitStateSnapshotUseCase:
    """Build the snapshot emission use case for the configured message backend."""
    if not hasattr(state_cache_port, "read_snapshot"):
        raise RuntimeError("Configured state cache does not support snapshot reads.")
    return EmitStateSnapshotUseCase(
        snapshot_reader_port=cast(SourceStateSnapshotReaderPort, state_cache_port),
        publisher=_build_message_publisher(),
    )


def _build_message_publisher() -> MessagePublisherPort:
    """Build the configured snapshot message publisher adapter."""
    if isinstance(CONFIG.message, RelationalOutboxMessageConfig):
        return RelationalOutboxMessagePublisher()
    if isinstance(CONFIG.message, RedisStreamsMessageConfig):
        return RedisStreamsMessagePublisher(settings=CONFIG.message)
    if isinstance(CONFIG.message, KafkaMessageConfig):
        return KafkaMessagePublisher(settings=CONFIG.message)
    raise RuntimeError(f"Unsupported message backend configured: {CONFIG.message!r}")


def main() -> int:
    """启动 ingest 运行时."""
    scheduler: SourceScheduler | None = None
    shutdown_event = Event()
    disposed = False

    def _dispose_once() -> None:
        nonlocal disposed
        if disposed:
            return
        dispose_engine()
        disposed = True

    def _shutdown(signum: int, frame: FrameType | None) -> None:
        """处理进程退出信号."""
        del frame
        print(f"[ingest] received signal {signum}, shutting down...")
        shutdown_event.set()

    signal.signal(signal.SIGINT, _shutdown)
    signal.signal(signal.SIGTERM, _shutdown)

    try:
        scheduler = build_scheduler()
        print("[ingest] starting scheduler...")
        scheduler.run()
        shutdown_event.wait()
        return 0
    except Exception as exc:
        print(f"[ingest] fatal error: {exc}", file=sys.stderr)
        return 1
    finally:
        if scheduler is not None:
            scheduler.stop(wait=True)
        _dispose_once()


if __name__ == "__main__":
    raise SystemExit(main())
