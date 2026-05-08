"""OPC UA read/subscribe adapter for inspecting one running simulated source."""

from __future__ import annotations

import asyncio
import inspect
from collections.abc import Callable, Sequence
from typing import Any

from asyncua import Client, Node, ua  # type: ignore[import-untyped]

from tools.source_simulation.domain import (
    SourceNodeInfo,
    SourceConnection,
    SourceReadPoint,
)

# 外部注入的数据变化处理函数类型。
# 支持两种：
# 1. 普通同步函数：def callback(node, val, data): ...
# 2. 异步函数：async def callback(node, val, data): ...
Callback = Callable[[Node, Any, Any], Any]


class OpcUaSubscriptionHandler:
    """OPC UA 订阅回调处理器。

    asyncua 的订阅回调方法 datachange_notification 是普通同步方法，
    因此这里不能直接 await 外部异步处理函数。

    处理策略：
    - 如果外部传入的是 async def，则用 asyncio.create_task 调度执行；
    - 如果外部传入的是普通 def，则用 asyncio.to_thread 放到线程池执行；
    - 保存 task，便于订阅退出时统一取消。
    """

    def __init__(self, on_data_change: Callback) -> None:
        self._on_data_change = on_data_change

        # 保存尚未完成的异步任务，便于优雅退出时统一清理。
        self._tasks: set[asyncio.Task[Any]] = set()

        # 判断外部传入的处理函数是否为 async def。
        self._is_async_callback = inspect.iscoroutinefunction(on_data_change)

    def datachange_notification(self, node: Node, val: Any, data: Any) -> None:
        """OPC UA 数据变化通知回调。

        这个方法由 asyncua 内部调用。
        注意：这里是同步函数，不能直接写 await。
        """

        if self._is_async_callback:
            # 外部处理函数是 async def：
            # 直接创建异步任务，让 event loop 后续调度执行。
            task = asyncio.create_task(self._on_data_change(node, val, data))
        else:
            # 外部处理函数是普通 def：
            # 放入线程池执行，避免同步 I/O 阻塞 event loop。
            task = asyncio.create_task(
                asyncio.to_thread(
                    self._on_data_change,
                    node,
                    val,
                    data,
                )
            )

        # 记录任务，避免无法管理未完成任务。
        self._tasks.add(task)

        # 任务完成后，自动从集合中移除，避免集合无限增长。
        task.add_done_callback(self._tasks.discard)

    async def cancel_pending(self) -> None:
        """取消所有尚未完成的外部回调任务。"""

        if not self._tasks:
            return

        for task in self._tasks:
            task.cancel()

        # return_exceptions=True：避免某个任务取消异常影响整体清理流程。
        await asyncio.gather(*self._tasks, return_exceptions=True)

        self._tasks.clear()


class OpcUaSourceReader:
    """OPC UA 数据读取与订阅客户端。

    用于集成测试、诊断工具或仿真数据读取。
    """

    def __init__(self, connection: SourceConnection) -> None:
        self._connection = connection
        self._client: Client | None = None

        # namespace index 需要连接 server 后，根据 namespace_uri 查询得到。
        self._nsidx: int | None = None

        # 这是 OPC UA client 会话内的技术缓存，只缓存 Node 对象；
        # 不保存点位值、质量、时间戳等业务状态，也不改变 reader 的业务无状态语义。
        self._node_cache: dict[str, Node] = {}

    @property
    def connection(self) -> SourceConnection:
        return self._connection

    @property
    def endpoint(self) -> str:
        """根据 SourceConnection 生成 OPC UA endpoint。"""

        transport = self._connection.transport.strip().lower()
        return f"opc.{transport}://{self._connection.host}:{self._connection.port}"

    async def __aenter__(self) -> "OpcUaSourceReader":
        """进入异步上下文，连接 OPC UA Server。"""

        client = Client(self.endpoint)
        await client.connect()

        self._client = client

        # 如果配置了 namespace_uri，则查询对应的 namespace index。
        namespace_uri = self._connection.namespace_uri or self._connection.params.get(
            "namespace_uri"
        )
        if namespace_uri is not None:
            self._nsidx = await client.get_namespace_index(str(namespace_uri))

        return self

    async def __aexit__(self, exc_type: object, exc: object, tb: object) -> None:
        """退出异步上下文，断开 OPC UA 连接。"""

        try:
            if self._client is not None:
                await self._client.disconnect()
        finally:
            # 连接结束后清空会话内 Node 缓存，避免跨连接复用失效 Node。
            self._client = None
            self._nsidx = None
            self._node_cache.clear()

    async def read(
        self,
        node_paths: Sequence[str],
        *,
        fast_mode: bool = True,
    ) -> tuple[SourceReadPoint, ...]:
        """读取一批节点数据。

        fast_mode=True:
            使用 read_values，只返回裸值，数据量较小。

        fast_mode=False:
            使用 read_attributes(Value)，返回 DataValue，
            可获取 status、source_timestamp、server_timestamp。
        """

        normalized_paths = self._normalize_node_paths(node_paths)

        if fast_mode:
            return await self._read_via_read_values(normalized_paths)

        return await self._read_via_read_attributes(normalized_paths)

    async def list_nodes(self) -> tuple[SourceNodeInfo, ...]:
        """Return readable variable nodes with full path, type, and LD/LN/DO parts."""

        client = self._client_or_raise()
        if self._nsidx is None:
            raise RuntimeError(
                "Namespace index is not initialized. "
                "Please provide namespace_uri in connection.params."
            )

        windfarm = await client.nodes.objects.get_child(f"{self._nsidx}:WindFarm")
        return await self._collect_variable_node_infos(windfarm)

    async def list_readable_variable_nodes(self) -> tuple[tuple[str, str], ...]:
        """Return all readable variable node ids and normalized types under WindFarm."""

        return tuple((node.node_path, node.data_type) for node in await self.list_nodes())

    async def subscribe(
        self,
        node_paths: Sequence[str],
        *,
        interval_ms: int,
        on_data_change: Callback,
    ) -> None:
        """订阅一批节点的数据变化。

        外部通过 on_data_change 注入处理逻辑，例如：
        - 写 Redis
        - 写 Kafka
        - 更新本地缓存
        - 打印日志

        on_data_change 可以是同步函数，也可以是异步函数。
        """

        client = self._client_or_raise()

        normalized_paths = self._normalize_node_paths(node_paths)
        nodes = self._get_nodes(normalized_paths)

        # 创建订阅处理器，外部处理函数注入到 handler 内部。
        handler = OpcUaSubscriptionHandler(on_data_change)

        # 创建 OPC UA Subscription。
        # interval_ms 是 publishing interval，单位通常为毫秒。
        subscription = await client.create_subscription(
            interval_ms,
            handler,
        )

        # 订阅多个节点的数据变化。
        handles = await subscription.subscribe_data_change(nodes)

        try:
            # 保持订阅任务持续运行。
            # 外部取消该 coroutine 时，会进入 finally 做清理。
            while True:
                await asyncio.sleep(1)

        except asyncio.CancelledError:
            # 保留取消语义，让上层知道 subscribe 被取消。
            raise

        finally:
            # 取消 OPC UA 订阅。
            await subscription.unsubscribe(handles)

            # 删除 Subscription。
            await subscription.delete()

            # 清理 handler 中尚未完成的外部处理任务。
            await handler.cancel_pending()

    def _client_or_raise(self) -> Client:
        """获取已连接的 OPC UA Client。"""

        if self._client is None:
            raise RuntimeError("Source reader must be connected before reading/subscribing")

        return self._client

    def _get_nodes(self, node_paths: Sequence[str]) -> list[Node]:
        """返回当前会话内可复用的 Node 对象列表。"""

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
        """将节点路径统一转换为完整 NodeId 字符串。

        如果传入路径已经以 ns= 开头，则认为它已经是完整 NodeId。
        否则自动补充 ns={namespace_index}; 前缀。
        """

        return tuple(
            path if path.startswith("ns=") else self._with_namespace_index(path)
            for path in node_paths
        )

    def _with_namespace_index(self, node_path: str) -> str:
        """给普通节点路径补充 namespace index。"""

        if self._nsidx is None:
            raise RuntimeError(
                "Namespace index is not initialized. "
                "Please provide namespace_uri in connection.params."
            )

        return f"ns={self._nsidx};{node_path}"

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
        """通过 read_values 批量读取裸值。"""

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
        """通过 read_attributes 批量读取 DataValue。

        DataValue 中包含：
        - Value
        - StatusCode
        - SourceTimestamp
        - ServerTimestamp
        """

        client = self._client_or_raise()
        nodes = self._get_nodes(node_paths)

        data_values = await client.read_attributes(
            nodes,
            attr=ua.AttributeIds.Value,
        )

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
