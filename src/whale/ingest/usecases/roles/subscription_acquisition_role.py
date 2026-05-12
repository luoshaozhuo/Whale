"""SubscriptionAcquisitionRole — 启动订阅采集 session。

设计约定：
- SUBSCRIBE 启动前必须先 read 一次完整基准状态；
- initial read baseline 用于填充 latest-state cache；
- 后续 datachange 只做增量 batch 覆盖；
- 订阅 notification 的 queue / micro-batch 在 source_reader 内处理；
- 本 role 只负责订阅采集策略编排；
- 参数合法性由 SourceAcquisitionUseCase 保证。
"""

from __future__ import annotations

import asyncio
import contextlib
from dataclasses import dataclass
from datetime import UTC, datetime

from whale.ingest.ports.source.source_acquisition_port import (
    SourceAcquisitionPort,
    SourceSubscriptionHandle,
    SubscriptionStateHandler,
)
from whale.ingest.ports.state.source_state_cache_port import SourceStateCachePort
from whale.ingest.usecases.dtos.acquired_node_state import AcquiredNodeStateBatch
from whale.ingest.usecases.dtos.source_acquisition_request import (
    SourceAcquisitionRequest,
)
from whale.ingest.usecases.dtos.source_acquisition_start_result import (
    SourceAcquisitionStartResult,
)
from whale.ingest.usecases.dtos.source_connection_data import SourceConnectionData


@dataclass(slots=True)
class SubscriptionAcquisitionSession:
    """运行中的订阅采集会话。"""

    handle: SourceSubscriptionHandle
    closed: bool = False

    async def close(self) -> None:
        """关闭订阅采集会话。"""

        if self.closed:
            return

        self.closed = True
        await self.handle.close()


class SubscriptionAcquisitionRole:
    """启动协议订阅，并返回统一启动结果。"""

    def __init__(
        self,
        *,
        acquisition_port: SourceAcquisitionPort,
        state_cache_port: SourceStateCachePort,
    ) -> None:
        self._acquisition_port = acquisition_port
        self._state_cache_port = state_cache_port

    async def start(
        self,
        request: SourceAcquisitionRequest,
    ) -> SourceAcquisitionStartResult:
        """为 request.connections 中的全部 connection 启动订阅。"""

        sessions: list[SubscriptionAcquisitionSession] = []
        start_interval_seconds = (
            request.execution.subscription_start_interval_ms / 1000
        )

        for index, connection in enumerate(request.connections):
            if index > 0 and start_interval_seconds > 0:
                await asyncio.sleep(start_interval_seconds)

            try:
                await self._read_initial_baseline(
                    request=request,
                    connection=connection,
                )

                handle = await self._acquisition_port.start_subscription(
                    request.execution,
                    connection,
                    list(request.items),
                    state_received=self._build_state_received_handler(
                        connection=connection,
                    ),
                )
                sessions.append(SubscriptionAcquisitionSession(handle=handle))

            except Exception:
                self._state_cache_port.mark_unavailable(
                    ld_name=connection.ld_name,
                    status="ERROR",
                    observed_at=_utc_now(),
                    reason="subscription start failed",
                )
                await self._close_sessions(sessions)
                raise

        return SourceAcquisitionStartResult(
            request_id=request.request_id,
            task_id=request.task_id,
            mode=request.execution.acquisition_mode.upper(),
            sessions=sessions,
        )

    async def _read_initial_baseline(
        self,
        *,
        request: SourceAcquisitionRequest,
        connection: SourceConnectionData,
    ) -> None:
        """订阅启动前读取一次完整基准状态。"""

        batch = await self._acquisition_port.read(
            request.execution,
            connection,
            list(request.items),
        )

        self._update_batch(
            ld_name=connection.ld_name,
            batch=batch,
        )

        self._state_cache_port.mark_alive(
            ld_name=connection.ld_name,
            observed_at=batch.client_processed_at,
        )

    def _build_state_received_handler(
        self,
        *,
        connection: SourceConnectionData,
    ) -> SubscriptionStateHandler:
        """构造绑定当前 connection 的订阅回调。"""

        async def _state_received(batch: AcquiredNodeStateBatch) -> None:
            self._update_batch(
                ld_name=connection.ld_name,
                batch=batch,
            )
            self._state_cache_port.mark_alive(
                ld_name=connection.ld_name,
                observed_at=batch.client_processed_at,
            )

        return _state_received

    def _update_batch(
        self,
        *,
        ld_name: str,
        batch: AcquiredNodeStateBatch,
    ) -> int:
        """更新 latest-state cache。"""

        if batch.is_empty():
            return 0

        return self._state_cache_port.update(
            ld_name=ld_name,
            batch=batch,
        )

    @staticmethod
    async def _close_sessions(
        sessions: list[SubscriptionAcquisitionSession],
    ) -> None:
        """启动过程中发生异常时关闭已启动的订阅 session。"""

        for session in reversed(sessions):
            with contextlib.suppress(Exception):
                await session.close()


def _utc_now() -> datetime:
    """返回当前 UTC 时间。"""

    return datetime.now(tz=UTC)