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
from types import FrameType

from whale.ingest.adapters.config.opcua_source_acquisition_definition_repository import (
    OpcUaSourceAcquisitionDefinitionRepository,
)
from whale.ingest.adapters.config.source_runtime_config_repository import (
    SourceRuntimeConfigRepository,
)
from whale.ingest.adapters.source.opcua_source_acquisition_adapter import (
    OpcUaSourceAcquisitionAdapter,
)
from whale.ingest.adapters.store.sqlite_source_state_repository import (
    SqliteSourceStateRepository,
)
from whale.ingest.framework.persistence.session import dispose_engine
from whale.ingest.runtime.scheduler import SourceScheduler
from whale.ingest.runtime.scheduler_settings import SchedulerSettings
from whale.ingest.usecases.refresh_source_state_usecase import (
    RefreshSourceStateUseCase,
)


def build_scheduler() -> SourceScheduler:
    """构建 scheduler 及其依赖."""
    runtime_config_port = SourceRuntimeConfigRepository()
    acquisition_definition_port = OpcUaSourceAcquisitionDefinitionRepository()
    acquisition_port = OpcUaSourceAcquisitionAdapter()
    source_state_repository_port = SqliteSourceStateRepository()

    refresh_source_state_usecase = RefreshSourceStateUseCase(
        runtime_config_port=runtime_config_port,
        acquisition_definition_port=acquisition_definition_port,
        acquisition_port=acquisition_port,
        store_port=source_state_repository_port,
    )

    return SourceScheduler(
        runtime_config_port=runtime_config_port,
        refresh_source_state_usecase=refresh_source_state_usecase,
        settings=SchedulerSettings(scheduler_type="background"),
    )


def main() -> int:
    """启动 ingest 运行时."""
    scheduler = build_scheduler()
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
        try:
            scheduler.stop(wait=True)
        finally:
            _dispose_once()
        raise SystemExit(0)

    signal.signal(signal.SIGINT, _shutdown)
    signal.signal(signal.SIGTERM, _shutdown)

    try:
        print("[ingest] starting scheduler...")
        scheduler.run()
        if not scheduler.wait_until_terminal(timeout_seconds=30.0):
            print("[ingest] timed out waiting for scheduler jobs to finish", file=sys.stderr)
            return 1
        if scheduler.has_failures():
            for runtime_job in scheduler.get_runtime_jobs():
                result_status = (
                    runtime_job.last_result.status
                    if runtime_job.last_result is not None
                    else "UNKNOWN"
                )
                print(
                    "[ingest] job "
                    f"{runtime_job.aps_job_id} "
                    f"runtime_config_id={runtime_job.runtime_config.runtime_config_id} "
                    f"status={runtime_job.status} "
                    f"result_status={result_status}",
                    file=sys.stderr,
                )
            print("[ingest] one or more scheduler jobs failed", file=sys.stderr)
            return 1
        scheduler.stop(wait=True)
        return 0
    except Exception as exc:
        print(f"[ingest] fatal error: {exc}", file=sys.stderr)
        try:
            scheduler.stop(wait=False)
        finally:
            _dispose_once()
        return 1
    finally:
        _dispose_once()


if __name__ == "__main__":
    raise SystemExit(main())
