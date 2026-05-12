"""
OpcUaSubscriptionHandler 模块
==============================

该模块实现 OPC UA 订阅回调处理器，功能包括：
1. micro-batch flush 与 baseline read 使用统一 callback
2. baseline read 不加入 pending 队列，直接 callback
3. 网络异常 batch、baseline read batch 在 lock 内调用 callback，带超时保护
4. callback 周期可控，事件循环安全
5. pending 队列容量根据订阅节点数量动态
"""

from __future__ import annotations
import asyncio
from collections import deque
from datetime import datetime, timezone
from typing import Any, List

from asyncua import Node  # type: ignore[import-untyped]
from whale.shared.source.models import Batch, NodeValueChange, SubscriptionCallback
from whale.shared.source.opcua.reader import OpcUaSourceReader
from contextlib import asynccontextmanager


@asynccontextmanager
async def lock_with_timeout(lock: asyncio.Lock, timeout: float):
    """Async context manager for asyncio.Lock with timeout."""
    await asyncio.wait_for(lock.acquire(), timeout=timeout)
    try:
        yield
    finally:
        lock.release()


class OpcUaSubscriptionHandler:
    """OPC UA 订阅回调处理器.

    Attributes:
        _on_data_change: 下游统一 callback
        _reader: 所属 reader，用于 baseline read / 异常 flush
        _pending_subscription: pending 队列，用于 micro-batch flush
        _callback_lock: 异步锁，保护 callback 调用
        _callback_lock_timeout: callback 超时
        _last_received_at: 最近一次接收订阅数据时间
        _flush_scheduled: 是否已调度 flush
        _closed: handler 是否已关闭
        _monitor_task: 网络监控异步任务
        _is_async_callback: 下游 callback 是否为协程
    """

    def __init__(
        self,
        on_data_change: SubscriptionCallback,
        reader: OpcUaSourceReader | None = None,
        subscription_node_count: int | None = None,
    ) -> None:
        """初始化 OpcUaSubscriptionHandler.

        Args:
            on_data_change: 下游统一 callback
            reader: 所属 reader，用于 baseline read / 异常 flush
            subscription_node_count: 订阅节点数量，用于动态设置 pending 队列容量
        """
        self._on_data_change = on_data_change
        self._is_async_callback = asyncio.iscoroutinefunction(on_data_change)
        self._reader = reader
        self._last_received_at: datetime | None = None
        self._flush_scheduled = False
        self._closed = False
        self._client_sequence = 0

        publish_interval_ms = getattr(reader, "_publish_interval_ms", 100)
        node_count = subscription_node_count or 1000
        self._pending_subscription = deque(maxlen=node_count)
        self._callback_lock = asyncio.Lock()
        self._callback_lock_timeout = max(len(self._pending_subscription) * 0.001, 0.05)
        self._max_lag_ms = max(publish_interval_ms * 2 + 50, 500)
        self._sleep_interval_s = max(publish_interval_ms / 1000 * 1.5, 0.5)

        self._monitor_task = None
        if reader:
            self._monitor_task = asyncio.create_task(self._network_monitor_loop())

    def datachange_notification(self, node: Node, val: Any, data: Any) -> None:
        """接收节点变化，插入队列并调度 flush.

        Args:
            node: OPC UA 节点
            val: 节点值
            data: 节点状态数据
        """
        if self._closed:
            return

        self._client_sequence += 1
        now = datetime.now(timezone.utc)
        self._last_received_at = now

        change = NodeValueChange(
            node_key=self._node_id_to_string(node),
            value=val,
            quality=self._resolve_status(data),
            source_timestamp=self._resolve_source_timestamp(data),
            server_timestamp=self._resolve_server_timestamp(data),
            client_sequence=self._client_sequence,
            attributes={"source": "subscription"},
        )

        self._pending_subscription.appendleft(change)
        if not self._flush_scheduled:
            self._flush_scheduled = True
            asyncio.get_running_loop().call_soon(self._schedule_dispatch)

    def _schedule_dispatch(self) -> None:
        """调度 _dispatch_pending 执行 flush."""
        self._flush_scheduled = False
        if not self._closed and self._pending_subscription:
            asyncio.ensure_future(self._dispatch_pending())

    async def _dispatch_pending(self) -> None:
        """Flush pending subscription 并调用下游 callback."""
        changes = list(self._pending_subscription)
        self._pending_subscription.clear()

        # 去重并获取最早 source_timestamp
        deduped, observed = self._deduplicate_and_observed(changes)
        now = datetime.now(timezone.utc)

        batch = Batch(
            changes=tuple(deduped),
            batch_observed_at=observed,
            client_received_at=now,
            availability_status="VALID",
        )

        async with lock_with_timeout(self._callback_lock, self._callback_lock_timeout):
            if self._is_async_callback:
                await self._on_data_change(batch)
            else:
                await asyncio.to_thread(self._on_data_change, batch)
            self._last_received_at = now

    async def _network_monitor_loop(self) -> None:
        """监控网络滞后 / 中断，生成异常 batch 并触发 baseline read flush."""
        try:
            while not self._closed:
                await asyncio.sleep(self._sleep_interval_s)
                if self._last_received_at is None:
                    continue

                now = datetime.now(timezone.utc)
                elapsed_ms = (now - self._last_received_at).total_seconds() * 1000
                if elapsed_ms > self._max_lag_ms and self._reader:
                    batch: Batch
                    try:
                        batch = await asyncio.wait_for(
                            self._reader.read([], mode="full"),
                            timeout=self._callback_lock_timeout
                        )
                        batch.availability_status = "STALE"
                    except Exception as ex:
                        batch = Batch(
                            changes=(),
                            batch_observed_at=now,
                            client_received_at=now,
                            availability_status="OFFLINE",
                            attributes={
                                "reason": "baseline_read_failed",
                                "exception": str(ex),
                                "retry_count": 0,
                            },
                        )
                    finally:
                        async with lock_with_timeout(self._callback_lock, self._callback_lock_timeout):
                            if self._is_async_callback:
                                await self._on_data_change(batch)
                            else:
                                await asyncio.to_thread(self._on_data_change, batch)
                            self._last_received_at = now

        except asyncio.CancelledError:
            pass

    async def close(self) -> None:
        """关闭 handler 并清空 pending 队列."""
        self._closed = True
        self._pending_subscription.clear()
        if self._monitor_task:
            self._monitor_task.cancel()
            try:
                await self._monitor_task
            except asyncio.CancelledError:
                pass

    # -----------------
    # 辅助方法
    # -----------------
    @staticmethod
    def _node_id_to_string(node: Node) -> str:
        """将 Node 转为唯一字符串标识"""
        node_id = getattr(node, "nodeid", node)
        if hasattr(node_id, "to_string"):
            return str(node_id.to_string())
        return str(node_id)

    @staticmethod
    def _resolve_status(data: object) -> str | None:
        """获取节点数据质量标记"""
        mi = getattr(data, "monitored_item", None)
        value = getattr(mi, "Value", None)
        status = getattr(value, "StatusCode", None)
        return str(status) if status is not None else None

    @staticmethod
    def _resolve_source_timestamp(data: object) -> datetime | None:
        """获取节点采集端时间戳"""
        mi = getattr(data, "monitored_item", None)
        value = getattr(mi, "Value", None)
        ts = getattr(value, "SourceTimestamp", None)
        return ts if isinstance(ts, datetime) else None

    @staticmethod
    def _resolve_server_timestamp(data: object) -> datetime | None:
        """获取节点服务器时间戳"""
        mi = getattr(data, "monitored_item", None)
        value = getattr(mi, "Value", None)
        ts = getattr(value, "ServerTimestamp", None)
        return ts if isinstance(ts, datetime) else None

    @staticmethod
    def _deduplicate_and_observed(changes: List[NodeValueChange]) -> tuple[List[NodeValueChange], datetime]:
        """按 node_key 去重，保留 client_sequence 最大，同时返回最早 source_timestamp."""
        latest: dict[str, NodeValueChange] = {}
        earliest_ts: datetime | None = None

        for c in changes:
            # 去重：保留 client_sequence 最大
            key = c.node_key
            if key not in latest or (c.client_sequence or 0) >= (latest[key].client_sequence or 0):
                latest[key] = c

            # 找最早 source_timestamp
            ts = c.source_timestamp
            if ts is not None:
                if earliest_ts is None or ts < earliest_ts:
                    earliest_ts = ts

        deduped = list(latest.values())

        # 如果所有节点都没有 source_timestamp，用当前 UTC
        if earliest_ts is None:
            earliest_ts = datetime.now(timezone.utc)

        return deduped, earliest_ts