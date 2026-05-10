"""SubscriptionAcquisitionRole — 启动订阅采集 session。"""

from __future__ import annotations

import asyncio
import contextlib
from dataclasses import dataclass

from whale.ingest.ports.source.source_acquisition_port import (
    SourceAcquisitionPort,
    SourceSubscriptionHandle,
    SubscriptionStateHandler,
)
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
    """启动协议订阅，并返回统一启动结果。

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
                with contextlib.suppress(asyncio.TimeoutError):
                    await asyncio.wait_for(
                        asyncio.Event().wait(),
                        timeout=start_interval_seconds,
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

        return SourceAcquisitionStartResult(
            request_id=request.request_id,
            task_id=request.task_id,
            mode=request.execution.acquisition_mode.upper(),
            sessions=sessions,
        )

    def _build_state_received_handler(
        self,
        *,
        connection: SourceConnectionData,
    ) -> SubscriptionStateHandler:
        """构造绑定当前 connection 的订阅回调。"""

        async def _state_received(acquired_states: list[AcquiredNodeState]) -> None:
            self._update_states(
                ld_name=connection.ld_name,
                states=list(acquired_states),
            )

        return _state_received

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