"""PollingAcquisitionRole — 主动采集循环 role。

READ_ONCE / ONCE 由 max_iteration=1 表达。
POLLING 由 max_iteration=None 或 max_iteration>1 表达。
"""

from __future__ import annotations

import asyncio
import contextlib
import time
from dataclasses import dataclass

from whale.ingest.ports.source.source_acquisition_port import SourceAcquisitionPort
from whale.ingest.ports.state.source_state_cache_port import SourceStateCachePort
from whale.ingest.usecases.dtos.acquired_node_state import AcquiredNodeState
from whale.ingest.usecases.dtos.source_acquisition_request import (
    SourceAcquisitionRequest,
)
from whale.ingest.usecases.dtos.source_acquisition_start_result import (
    SourceAcquisitionStartResult,
)
from whale.ingest.usecases.dtos.source_connection_data import SourceConnectionData


@dataclass(slots=True)
class PollingAcquisitionSession:
    """运行中的主动采集 session。"""

    task: asyncio.Task[None]
    stop_event: asyncio.Event
    closed: bool = False

    async def close(self) -> None:
        """停止后台 task。"""

        if self.closed:
            return

        self.closed = True
        self.stop_event.set()
        await self.task


class PollingAcquisitionRole:
    """主动采集循环 role。

    本 role 只执行主动采集策略。
    参数合法性由 SourceAcquisitionUseCase 保证。
    """

    def __init__(
        self,
        *,
        acquisition_port: SourceAcquisitionPort,
        state_cache_port: SourceStateCachePort,
    ) -> None:
        self._acquisition_port = acquisition_port
        self._state_cache_port = state_cache_port

    def start(
        self,
        request: SourceAcquisitionRequest,
    ) -> SourceAcquisitionStartResult:
        """启动主动采集循环，并立即返回统一启动结果。"""

        stop_event = asyncio.Event()
        task = asyncio.create_task(
            self._run_loop(
                request=request,
                stop_event=stop_event,
            )
        )

        return SourceAcquisitionStartResult(
            request_id=request.request_id,
            task_id=request.task_id,
            mode=request.execution.acquisition_mode.upper(),
            sessions=[
                PollingAcquisitionSession(
                    task=task,
                    stop_event=stop_event,
                )
            ],
        )

    async def _run_loop(
        self,
        *,
        request: SourceAcquisitionRequest,
        stop_event: asyncio.Event,
    ) -> None:
        """后台主动采集循环。"""

        interval_seconds = request.execution.interval_ms / 1000
        remaining_iterations = request.execution.max_iteration

        while not stop_event.is_set():
            cycle_started_at = time.monotonic()

            await self._read_all_connections(
                request=request,
                stop_event=stop_event,
            )

            if remaining_iterations is not None:
                remaining_iterations -= 1
                if remaining_iterations <= 0:
                    return

            elapsed = time.monotonic() - cycle_started_at
            wait_seconds = max(0.0, interval_seconds - elapsed)

            if wait_seconds <= 0:
                # TODO: 后续记录 polling cycle overrun。
                continue

            with contextlib.suppress(asyncio.TimeoutError):
                await asyncio.wait_for(
                    stop_event.wait(),
                    timeout=wait_seconds,
                )

    async def _read_all_connections(
        self,
        *,
        request: SourceAcquisitionRequest,
        stop_event: asyncio.Event,
    ) -> None:
        """读取全部 connection。

        不拆分 items。
        只在 connection 级别做错峰与并发上限控制。
        """

        semaphore = asyncio.Semaphore(
            request.execution.polling_max_concurrent_connections
        )
        start_interval_seconds = (
            request.execution.polling_connection_start_interval_ms / 1000
        )

        await asyncio.gather(
            *(
                self._read_connection_with_offset(
                    request=request,
                    connection=connection,
                    start_offset_seconds=index * start_interval_seconds,
                    semaphore=semaphore,
                    stop_event=stop_event,
                )
                for index, connection in enumerate(request.connections)
            )
        )

    async def _read_connection_with_offset(
        self,
        *,
        request: SourceAcquisitionRequest,
        connection: SourceConnectionData,
        start_offset_seconds: float,
        semaphore: asyncio.Semaphore,
        stop_event: asyncio.Event,
    ) -> None:
        """按 connection 错峰后读取单个 connection。"""

        if start_offset_seconds > 0:
            with contextlib.suppress(asyncio.TimeoutError):
                await asyncio.wait_for(
                    stop_event.wait(),
                    timeout=start_offset_seconds,
                )

            if stop_event.is_set():
                return

        async with semaphore:
            if stop_event.is_set():
                return

            await self._read_connection(
                request=request,
                connection=connection,
            )

    async def _read_connection(
        self,
        *,
        request: SourceAcquisitionRequest,
        connection: SourceConnectionData,
    ) -> None:
        """读取单个 connection，并更新 latest-state cache。"""

        try:
            states = await self._acquisition_port.read(
                request.execution,
                connection,
                list(request.items),
            )

            self._update_states(
                ld_name=connection.ld_name,
                states=list(states),
            )

        except Exception:
            # TODO: 后续在这里记录采集异常：
            # - request_id = request.request_id
            # - task_id = request.task_id
            # - connection.ld_name / connection.ied_name
            # - exception 类型与消息
            pass
            raise

    def _update_states(
        self,
        *,
        ld_name: str,
        states: list[AcquiredNodeState],
    ) -> int:
        """更新 latest-state cache。"""

        if not states:
            return 0

        return self._state_cache_port.update(
            ld_name=ld_name,
            states=states,
        )