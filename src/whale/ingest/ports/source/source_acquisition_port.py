"""Source acquisition port for ingest."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Protocol

from whale.ingest.usecases.dtos.acquired_node_state import AcquiredNodeState
from whale.ingest.usecases.dtos.source_acquisition_request import (
    AcquisitionExecutionOptions,
    AcquisitionItemData,
)
from whale.ingest.usecases.dtos.source_connection_data import SourceConnectionData


SubscriptionStateHandler = Callable[[list[AcquiredNodeState]], Awaitable[None]]


class SourceSubscriptionHandle(Protocol):
    """协议层订阅句柄。"""

    async def close(self) -> None:
        """停止订阅并释放底层资源。"""


class SourceAcquisitionPort(Protocol):
    """Acquire source states from one configured source."""

    async def read(
        self,
        execution: AcquisitionExecutionOptions,
        connection: SourceConnectionData,
        items: list[AcquisitionItemData],
    ) -> list[AcquiredNodeState]:
        """Acquire a batch of source states for one source."""

    async def start_subscription(
        self,
        execution: AcquisitionExecutionOptions,
        connection: SourceConnectionData,
        items: list[AcquisitionItemData],
        *,
        state_received: SubscriptionStateHandler,
    ) -> SourceSubscriptionHandle:
        """启动订阅并立即返回订阅句柄。"""
