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

from whale.ingest.adapters.config.source_connection_config_repository import (
    SourceConnectionConfigRepository,
)
from whale.ingest.adapters.config.source_schedule_config_repository import (
    SourceScheduleConfigRepository,
)
from whale.ingest.adapters.source.opcua_source_acquisition_adapter import (
    OpcUaSourceAcquisitionAdapter,
)
from whale.ingest.adapters.store.counting_source_state_repository_adapter import (
    CountingSourceStateRepositoryAdapter,
)
from whale.ingest.framework.persistence.session import dispose_engine
from whale.ingest.runtime.scheduler import SourceScheduler
from whale.ingest.usecases.maintain_source_state_usecase import (
    MaintainSourceStateUseCase,
)


def build_scheduler() -> SourceScheduler:
    """构建 scheduler 及其依赖。"""
    source_config_port = SourceConnectionConfigRepository()
    execution_plan_port = SourceScheduleConfigRepository()
    acquisition_port = OpcUaSourceAcquisitionAdapter()
    source_state_repository_port = CountingSourceStateRepositoryAdapter()

    maintain_source_state_usecase = MaintainSourceStateUseCase(
        source_config_port=source_config_port,
        acquisition_port=acquisition_port,
        store_port=source_state_repository_port,
    )

    return SourceScheduler(
        execution_plan_port=execution_plan_port,
        maintain_source_state_usecase=maintain_source_state_usecase,
    )


def main() -> int:
    """启动 ingest 运行时。"""
    scheduler = build_scheduler()
    disposed = False

    def _dispose_once() -> None:
        nonlocal disposed
        if disposed:
            return
        dispose_engine()
        disposed = True

    def _shutdown(signum: int, frame: FrameType | None) -> None:
        """处理进程退出信号。"""
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