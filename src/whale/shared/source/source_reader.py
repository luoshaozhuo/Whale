"""共享 OPC UA reader。

这个模块只负责协议层能力：
- 建立 OPC UA client 连接
- 规范化节点地址
- 批量读取节点
- 建立订阅并转发数据变化事件

它刻意不依赖 ingest 或 simulation 的业务 DTO。
这样 tools、ingest 以及后续其他程序都可以复用这一套实现，
避免在不同目录里维护多个 reader。
"""

from __future__ import annotations

import asyncio
import contextlib
import inspect
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from asyncua import Client, Node, ua  # type: ignore[import-untyped]


ConnectionParamValue = str | int | float | bool | None
SubscriptionCallback = Callable[[Node, Any, Any], Any]


@dataclass(frozen=True, slots=True)
class SourceConnectionProfile:
    """协议层连接参数。

    这里使用最小必要字段，避免把上层业务 DTO 或 tools 侧模型直接耦合进来。
    上层只需要把自己的连接模型转换成这个 profile 即可。
    """

    endpoint: str
    namespace_uri: str | None = None
    timeout_seconds: float = 4.0
    params: dict[str, ConnectionParamValue] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class SourceReadPoint:
    """一次读取返回的单点值。"""

    path: str
    value: Any
    status: str | None = None
    source_timestamp: datetime | None = None
    server_timestamp: datetime | None = None


@dataclass(frozen=True, slots=True)
class SourceNodeInfo:
    """一个可读变量节点的基本信息。"""

    node_path: str
    data_type: str
    ld_name: str
    ln_name: str
    do_name: str


@dataclass(frozen=True, slots=True)
class _QueuedDataChange:
    """进入客户端侧 notification 队列的数据变化事件。"""

    node: Node
    value: Any
    data: Any
    queued_at: float


class SubscriptionNotificationOverloadError(RuntimeError):
    """订阅 notification 队列过载。"""


class _OpcUaSubscriptionHandler:
    """OPC UA 订阅回调桥接器。

    asyncua 的 datachange_notification 是同步回调；
    这里将 notification 放入 bounded queue，再由固定 worker 消费。
    """

    def __init__(
        self,
        on_data_change: SubscriptionCallback,
        *,
        queue_size: int,
        worker_count: int,
        max_queue_lag_ms: int,
    ) -> None:
        if queue_size <= 0:
            raise ValueError("queue_size must be greater than 0")
        if worker_count <= 0:
            raise ValueError("worker_count must be greater than 0")
        if max_queue_lag_ms <= 0:
            raise ValueError("max_queue_lag_ms must be greater than 0")

        self._on_data_change = on_data_change
        self._is_async_callback = inspect.iscoroutinefunction(on_data_change)
        self._queue: asyncio.Queue[_QueuedDataChange | None] = asyncio.Queue(
            maxsize=queue_size
        )
        self._max_queue_lag_seconds = max_queue_lag_ms / 1000
        self._workers = [
            asyncio.create_task(self._run_worker(worker_index=index))
            for index in range(worker_count)
        ]
        self._overload_error: SubscriptionNotificationOverloadError | None = None
        self._closed = False

    def datachange_notification(self, node: Node, val: Any, data: Any) -> None:
        """接收 asyncua 的同步通知并放入 bounded queue。"""

        if self._closed:
            return

        event = _QueuedDataChange(
            node=node,
            value=val,
            data=data,
            queued_at=time.monotonic(),
        )

        try:
            self._queue.put_nowait(event)
        except asyncio.QueueFull as exc:
            self._overload_error = SubscriptionNotificationOverloadError(
                "subscription notification queue is full"
            )
            raise self._overload_error from exc

    async def close(self) -> None:
        """停止 workers，并回收尚未处理的 notification。"""

        if self._closed:
            return

        self._closed = True

        for _ in self._workers:
            with contextlib.suppress(asyncio.QueueFull):
                self._queue.put_nowait(None)

        await asyncio.gather(*self._workers, return_exceptions=True)

        while not self._queue.empty():
            self._queue.get_nowait()
            self._queue.task_done()

    async def _run_worker(self, *, worker_index: int) -> None:
        """固定 worker：从 queue 消费 notification 并调用外部回调。"""

        del worker_index

        while True:
            event = await self._queue.get()
            try:
                if event is None:
                    return

                lag_seconds = time.monotonic() - event.queued_at
                if lag_seconds > self._max_queue_lag_seconds:
                    self._overload_error = SubscriptionNotificationOverloadError(
                        "subscription notification queue lag exceeded"
                    )
                    continue

                await self._dispatch_callback(
                    node=event.node,
                    val=event.value,
                    data=event.data,
                )
            finally:
                self._queue.task_done()

    async def _dispatch_callback(self, *, node: Node, val: Any, data: Any) -> None:
        """调用外部 datachange callback。"""

        if self._is_async_callback:
            await self._on_data_change(node, val, data)
            return

        await asyncio.to_thread(
            self._on_data_change,
            node,
            val,
            data,
        )


@dataclass(slots=True)
class OpcUaSubscriptionHandle:
    """OPC UA 订阅句柄。

    由 OpcUaSourceReader.start_subscription() 返回。
    外部保存该句柄，并在需要停止订阅时调用 close()。
    """

    subscription: Any
    handles: Any
    handler: _OpcUaSubscriptionHandler
    closed: bool = False

    async def close(self) -> None:
        """停止订阅并释放订阅相关资源。

        close() 是幂等的，重复调用不会重复释放。
        """

        if self.closed:
            return

        self.closed = True

        try:
            await self.subscription.unsubscribe(self.handles)
        finally:
            try:
                await self.subscription.delete()
            finally:
                await self.handler.close()


class OpcUaSourceReader:
    """共享 OPC UA reader。

    这个类只处理协议层通信，不承载业务状态更新、缓存刷新等上层逻辑。
    """

    def __init__(self, connection: SourceConnectionProfile) -> None:
        self._connection = connection
        self._client: Client | None = None
        self._nsidx: int | None = None
        self._node_cache: dict[str, Node] = {}

    @property
    def endpoint(self) -> str:
        return self._connection.endpoint

    async def __aenter__(self) -> OpcUaSourceReader:
        """进入异步上下文并建立 OPC UA 会话。"""

        client = Client(self.endpoint, timeout=self._connection.timeout_seconds)
        await client.connect()

        self._client = client
        self._nsidx = await self._resolve_namespace_index(client)

        return self

    async def __aexit__(self, exc_type: object, exc: object, tb: object) -> None:
        """退出异步上下文并清理会话态缓存。"""

        try:
            if self._client is not None:
                await self._client.disconnect()
        finally:
            self._client = None
            self._nsidx = None
            self._node_cache.clear()

    async def read(
        self,
        node_paths: Sequence[str],
        *,
        fast_mode: bool = True,
    ) -> tuple[SourceReadPoint, ...]:
        """批量读取节点。

        - fast_mode=True 时走 read_values，返回值更轻量。
        - fast_mode=False 时走 read_attributes(Value)，保留状态和时间戳。
        """

        normalized_paths = self._normalize_node_paths(node_paths)

        if fast_mode:
            return await self._read_via_read_values(normalized_paths)

        return await self._read_via_read_attributes(normalized_paths)

    async def start_subscription(
        self,
        node_paths: Sequence[str],
        *,
        interval_ms: int,
        on_data_change: SubscriptionCallback,
    ) -> OpcUaSubscriptionHandle:
        """建立 OPC UA 订阅并立即返回订阅句柄。"""

        if interval_ms <= 0:
            raise ValueError("interval_ms must be greater than 0")

        client = self._client_or_raise()
        normalized_paths = self._normalize_node_paths(node_paths)
        nodes = self._get_nodes(normalized_paths)

        handler = _OpcUaSubscriptionHandler(
            on_data_change,
            queue_size=self._subscription_notification_queue_size(),
            worker_count=self._subscription_notification_worker_count(),
            max_queue_lag_ms=self._subscription_notification_max_lag_ms(),
        )
        subscription = await client.create_subscription(interval_ms, handler)
        handles = await subscription.subscribe_data_change(nodes)

        return OpcUaSubscriptionHandle(
            subscription=subscription,
            handles=handles,
            handler=handler,
        )

    async def list_nodes(self) -> tuple[SourceNodeInfo, ...]:
        """列出 WindFarm 下全部可读变量节点。"""

        client = self._client_or_raise()

        if self._nsidx is None:
            raise RuntimeError(
                "Namespace index is not initialized. "
                "Please provide namespace_uri in connection.params."
            )

        windfarm = await client.nodes.objects.get_child(f"{self._nsidx}:WindFarm")
        return await self._collect_variable_node_infos(windfarm)

    async def list_readable_variable_nodes(self) -> tuple[tuple[str, str], ...]:
        """返回全部变量节点路径和规范化数据类型。"""

        return tuple((node.node_path, node.data_type) for node in await self.list_nodes())

    async def _resolve_namespace_index(self, client: Client) -> int | None:
        """根据 namespace_uri 解析 namespace index。"""

        namespace_uri = self._connection.namespace_uri

        if namespace_uri is None:
            raw_namespace_uri = self._connection.params.get("namespace_uri")
            if isinstance(raw_namespace_uri, str) and raw_namespace_uri.strip():
                namespace_uri = raw_namespace_uri.strip()

        if namespace_uri is None:
            return None

        return await client.get_namespace_index(namespace_uri)

    def _client_or_raise(self) -> Client:
        if self._client is None:
            raise RuntimeError("Source reader must be connected before reading/subscribing")

        return self._client

    def _get_nodes(self, node_paths: Sequence[str]) -> list[Node]:
        client = self._client_or_raise()
        nodes: list[Node] = []

        for node_path in node_paths:
            node = self._node_cache.get(node_path)

            if node is None:
                node = client.get_node(node_path)
                self._node_cache[node_path] = node

            nodes.append(node)

        return nodes

    def _normalize_node_paths(self, node_paths: Sequence[str]) -> tuple[str, ...]:
        return tuple(
            path if path.startswith(("ns=", "nsu=")) else self._with_namespace_index(path)
            for path in node_paths
        )

    def _with_namespace_index(self, node_path: str) -> str:
        if self._nsidx is None:
            raise RuntimeError(
                "Namespace index is not initialized. "
                "Please provide namespace_uri in connection.params."
            )

        return f"ns={self._nsidx};{node_path}"

    def _subscription_notification_queue_size(self) -> int:
        return self._positive_int_param(
            "subscription_notification_queue_size",
            default=1000,
        )

    def _subscription_notification_worker_count(self) -> int:
        return self._positive_int_param(
            "subscription_notification_worker_count",
            default=1,
        )

    def _subscription_notification_max_lag_ms(self) -> int:
        return self._positive_int_param(
            "subscription_notification_max_lag_ms",
            default=5000,
        )

    def _positive_int_param(self, key: str, *, default: int) -> int:
        raw_value = self._connection.params.get(key)

        if raw_value is None:
            return default

        if isinstance(raw_value, bool):
            raise ValueError(f"{key} must be a positive integer")

        value = int(raw_value)

        if value <= 0:
            raise ValueError(f"{key} must be a positive integer")

        return value

    async def _collect_variable_node_infos(self, node: Node) -> tuple[SourceNodeInfo, ...]:
        node_infos: list[SourceNodeInfo] = []

        for child in await node.get_children():
            node_class = await child.read_node_class()

            if node_class == ua.NodeClass.Variable:
                node_path = self._node_id_to_string(child)
                node_infos.append(
                    SourceNodeInfo(
                        node_path=node_path,
                        data_type=await self._source_data_type_from_node(child),
                        ld_name=self._ld_name_from_node_path(node_path),
                        ln_name=self._ln_name_from_node_path(node_path),
                        do_name=self._do_name_from_node_path(node_path),
                    )
                )
                continue

            node_infos.extend(await self._collect_variable_node_infos(child))

        return tuple(node_infos)

    @staticmethod
    def _node_id_to_string(node: Node) -> str:
        node_id = getattr(node, "nodeid", None)

        if node_id is None:
            raise RuntimeError("Node is missing nodeid")

        if hasattr(node_id, "to_string"):
            return str(node_id.to_string())

        return str(node_id)

    async def _source_data_type_from_node(self, node: Node) -> str:
        data_type = await node.read_data_type()
        identifier = getattr(data_type, "Identifier", None)

        if identifier == 1:
            return "BOOLEAN"

        if identifier == 6:
            return "INT32"

        if identifier == 12:
            return "STRING"

        return "FLOAT64"

    @staticmethod
    def _logical_path_parts(node_path: str) -> tuple[str, str, str, str]:
        try:
            logical_path = node_path.split(";s=", maxsplit=1)[1]
            ied_name, ld_name, ln_name, do_name = logical_path.split(".", maxsplit=3)
        except (IndexError, ValueError) as exc:
            raise RuntimeError(f"Unexpected OPC UA node path format: {node_path}") from exc

        return ied_name, ld_name, ln_name, do_name

    @classmethod
    def _ld_name_from_node_path(cls, node_path: str) -> str:
        return cls._logical_path_parts(node_path)[1]

    @classmethod
    def _ln_name_from_node_path(cls, node_path: str) -> str:
        return cls._logical_path_parts(node_path)[2]

    @classmethod
    def _do_name_from_node_path(cls, node_path: str) -> str:
        return cls._logical_path_parts(node_path)[3]

    async def _read_via_read_values(
        self,
        node_paths: Sequence[str],
    ) -> tuple[SourceReadPoint, ...]:
        client = self._client_or_raise()
        nodes = self._get_nodes(node_paths)
        values = await client.read_values(nodes)

        return tuple(
            SourceReadPoint(
                path=node_path,
                value=value,
            )
            for node_path, value in zip(node_paths, values, strict=True)
        )

    async def _read_via_read_attributes(
        self,
        node_paths: Sequence[str],
    ) -> tuple[SourceReadPoint, ...]:
        client = self._client_or_raise()
        nodes = self._get_nodes(node_paths)
        data_values = await client.read_attributes(nodes, attr=ua.AttributeIds.Value)

        return tuple(
            SourceReadPoint(
                path=node_path,
                value=data_value.Value.Value if data_value.Value is not None else None,
                status=str(data_value.StatusCode) if data_value.StatusCode is not None else None,
                source_timestamp=data_value.SourceTimestamp,
                server_timestamp=data_value.ServerTimestamp,
            )
            for node_path, data_value in zip(node_paths, data_values, strict=True)
        )