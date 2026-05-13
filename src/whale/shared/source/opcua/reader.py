"""
OpcUaSourceReader 模块
======================

本文件实现 OPC UA 节点读取与订阅客户端，提供统一 Batch 回调接口：
1. 一次性 read（支持 full / value_only 模式）
2. subscription（内部 micro-batch flush、去重由 OpcUaSubscriptionHandler 管理）
3. baseline read（在 start_subscription 内部完成）
4. 下游统一 Batch 接口，无需区分 read 或 subscription
5. 所有 server 通信调用均支持超时和短重试
"""

from __future__ import annotations
import asyncio
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, List, Tuple, Literal

from asyncua import Client, Node, ua  # type: ignore[import-untyped]
from whale.shared.source.models import (
    Batch,
    NodeValueChange,
    SourceConnectionProfile,
    SourceNodeInfo,
    SubscriptionCallback,
)
from whale.shared.source.ports import SourceReaderPort, SourceSubscriptionHandlePort
from whale.shared.source.opcua.subscription import OpcUaSubscriptionHandler


@dataclass(slots=True)
class OpcUaSubscriptionHandle(SourceSubscriptionHandlePort):
    """OPC UA 订阅句柄，封装 subscription、handler 及状态."""

    subscription: Any
    handles: Any
    handler: OpcUaSubscriptionHandler
    closed: bool = False

    async def close(self) -> None:
        """停止订阅并释放相关资源."""
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


class OpcUaSourceReader(SourceReaderPort):
    """OPC UA 节点读取与订阅客户端.

    内部 micro-batch、网络异常、滞后等由 OpcUaSubscriptionHandler 管理。
    """

    def __init__(self, connection: SourceConnectionProfile) -> None:
        """初始化 OPC UA reader.

        Args:
            connection: 连接配置，包括 endpoint、namespace_uri、timeout、参数字典
        """
        self._connection = connection
        self._client: Client | None = None
        self._nsidx: int | None = None
        self._node_cache: Dict[str, Node] = {}
        self._subscriptions: List[OpcUaSubscriptionHandle] = []

    @property
    def endpoint(self) -> str:
        return self._connection.endpoint

    async def __aenter__(self) -> "OpcUaSourceReader":
        """异步上下文进入，建立 OPC UA 会话."""
        client = Client(self.endpoint, timeout=self._connection.timeout_seconds)
        await client.connect()
        self._client = client
        self._nsidx = await self._resolve_namespace_index(client)
        return self

    async def __aexit__(self, exc_type: object, exc: object, tb: object) -> None:
        """异步上下文退出，关闭订阅并断开连接."""
        for sub in self._subscriptions:
            await sub.close()
        try:
            if self._client is not None:
                await self._client.disconnect()
        finally:
            self._client = None
            self._nsidx = None
            self._node_cache.clear()
            self._subscriptions.clear()

    async def read(
        self,
        addresses: Sequence[str],
        *,
        mode: Literal["full", "value_only"] = "full",
    ) -> Batch:
        """一次性读取节点，返回统一 Batch 对象.

        Args:
            addresses: 待读取节点地址列表
            mode: 读取模式，"full" 返回 value + metadata，"value_only" 仅返回 value

        Returns:
            Batch: 节点状态和时间戳的统一对象
        """
        client = self._client_or_raise()
        normalized_paths = self._normalize_node_paths(addresses)
        nodes = self._get_nodes(normalized_paths)

        batch_changes: List[NodeValueChange] = []
        availability_status = "VALID"
        attributes: Dict[str, Any] = {}
        retry_count = 0
        max_retries = 1

        while retry_count <= max_retries:
            try:
                if mode == "value_only":
                    values = await asyncio.wait_for(
                        client.read_values(nodes),
                        timeout=self._connection.timeout_seconds
                    )
                    for path, val in zip(normalized_paths, values):
                        batch_changes.append(NodeValueChange(
                            node_key=path,
                            value=val,
                            quality=None,
                            source_timestamp=None,
                            server_timestamp=None,
                            client_sequence=0,
                            attributes={"value_only": True},
                        ))
                else:  # full mode
                    data_values = await asyncio.wait_for(
                        client.read_attributes(nodes, attr=ua.AttributeIds.Value),
                        timeout=self._connection.timeout_seconds
                    )
                    for idx, data_value in enumerate(data_values):
                        batch_changes.append(NodeValueChange(
                            node_key=normalized_paths[idx],
                            value=data_value.Value.Value if data_value.Value else None,
                            quality=str(data_value.StatusCode) if data_value.StatusCode else None,
                            source_timestamp=_raw_datetime(data_value.SourceTimestamp),
                            server_timestamp=_raw_datetime(data_value.ServerTimestamp),
                            client_sequence=0,
                            attributes={},
                        ))
                break
            except (asyncio.TimeoutError, Exception) as ex:
                retry_count += 1
                if retry_count > max_retries:
                    batch_changes = []
                    availability_status = "ERROR"
                    attributes = {
                        "reason": "timeout" if isinstance(ex, asyncio.TimeoutError) else "read_failed",
                        "exception": str(ex),
                        "retry_count": retry_count
                    }
                else:
                    await asyncio.sleep(0.05)  # 短暂退避

        now = datetime.now(tz=timezone.utc)
        return Batch(
            changes=tuple(batch_changes),
            batch_observed_at=now,
            client_received_at=now,
            availability_status=availability_status,
            attributes=attributes,
        )

    async def start_subscription(
        self,
        addresses: Sequence[str],
        *,
        interval_ms: int,
        on_data_change: SubscriptionCallback,
    ) -> OpcUaSubscriptionHandle:
        """启动 OPC UA subscription 并返回统一 batch 回调句柄.

        Args:
            addresses: 订阅节点地址列表
            interval_ms: 订阅周期，单位毫秒
            on_data_change: 数据变化回调函数

        Returns:
            OpcUaSubscriptionHandle: 订阅句柄
        """
        if interval_ms <= 0:
            raise ValueError("interval_ms must be greater than 0")
        client = self._client_or_raise()
        normalized_paths = self._normalize_node_paths(addresses)
        nodes = self._get_nodes(normalized_paths)

        # baseline read 内部调用 callback
        try:
            batch = await self.read(normalized_paths, mode="full")
            if batch.availability_status == "ERROR":
                attributes = dict(batch.attributes)
                attributes["reason"] = "baseline_read_failed"
                batch = Batch(
                    changes=batch.changes,
                    batch_observed_at=batch.batch_observed_at,
                    client_received_at=batch.client_received_at,
                    availability_status="ERROR",
                    attributes=attributes,
                )
        except Exception as ex:
            batch = Batch(
                changes=(),
                batch_observed_at=datetime.now(tz=timezone.utc),
                client_received_at=datetime.now(tz=timezone.utc),
                availability_status="ERROR",
                attributes={"reason": "baseline_read_failed", "exception": str(ex), "retry_count": 0}
            )
        await on_data_change(batch)

        handler = OpcUaSubscriptionHandler(on_data_change, reader=self)
        subscription = await asyncio.wait_for(
            client.create_subscription(interval_ms, handler),
            timeout=self._connection.timeout_seconds
        )
        handles = await asyncio.wait_for(
            subscription.subscribe_data_change(nodes),
            timeout=self._connection.timeout_seconds
        )

        sub_handle = OpcUaSubscriptionHandle(
            subscription=subscription,
            handles=handles,
            handler=handler
        )
        self._subscriptions.append(sub_handle)
        return sub_handle

    async def list_nodes(self) -> tuple[SourceNodeInfo, ...]:
        """列出当前 server 下全部可读变量节点及其元信息."""
        _ = self._client_or_raise()
        nsidx = self._nsidx
        if nsidx is None:
            raise RuntimeError("Namespace index not initialized")

        root = await self._resolve_browse_root(nsidx)
        variable_nodes = await self._collect_variable_nodes(root)

        node_infos: list[SourceNodeInfo] = []
        for variable_node in variable_nodes:
            node_path = _node_id_to_string(variable_node)
            identifier = _extract_string_identifier(node_path)
            ld_name, ln_name, do_name = _parse_logical_names(identifier)
            data_type = await self._read_node_data_type(variable_node)
            node_infos.append(
                SourceNodeInfo(
                    node_path=node_path,
                    data_type=data_type,
                    ld_name=ld_name,
                    ln_name=ln_name,
                    do_name=do_name,
                )
            )

        node_infos.sort(key=lambda item: item.node_path)
        return tuple(node_infos)

    async def list_readable_variable_nodes(self) -> tuple[tuple[str, str], ...]:
        """列出全部可读变量节点路径及规范化后的数据类型."""
        node_infos = await self.list_nodes()
        return tuple((item.node_path, item.data_type) for item in node_infos)

    # -----------------------
    # 辅助方法
    # -----------------------
    def _client_or_raise(self) -> Client:
        """获取已连接 OPC UA client，未连接则抛出异常."""
        if self._client is None:
            raise RuntimeError("OPC UA client is not connected")
        return self._client

    def _get_nodes(self, node_paths: Sequence[str]) -> List[Node]:
        """获取 Node 对象列表，缓存节点实例."""
        client = self._client_or_raise()
        nodes: List[Node] = []
        for path in node_paths:
            node = self._node_cache.get(path)
            if node is None:
                node = client.get_node(path)
                self._node_cache[path] = node
            nodes.append(node)
        return nodes

    def _normalize_node_paths(self, node_paths: Sequence[str]) -> Tuple[str, ...]:
        """标准化节点路径，添加 namespace index 前缀."""
        return tuple(
            path if path.startswith(("ns=", "nsu=")) else self._with_namespace_index(path)
            for path in node_paths
        )

    def _with_namespace_index(self, node_path: str) -> str:
        """为节点路径添加 namespace index."""
        if self._nsidx is None:
            raise RuntimeError("Namespace index not initialized")
        return f"ns={self._nsidx};{node_path}"

    async def _resolve_namespace_index(self, client: Client) -> int | None:
        """根据 namespace_uri 或 params 获取 namespace index."""
        namespace_uri = self._connection.namespace_uri or self._connection.params.get("namespace_uri")
        if not namespace_uri:
            return None
        return int(await client.get_namespace_index(namespace_uri))

    async def _resolve_browse_root(self, nsidx: int) -> Node:
        """优先定位 namespace 下业务根节点，找不到时回退到 Objects 根目录."""
        client = self._client_or_raise()
        objects_node = client.nodes.objects
        try:
            return await objects_node.get_child(f"{nsidx}:WindFarm")
        except Exception:
            return objects_node

    async def _collect_variable_nodes(self, root: Node) -> list[Node]:
        """递归遍历节点树，收集全部变量节点。"""
        stack: list[Node] = [root]
        variable_nodes: list[Node] = []
        while stack:
            current = stack.pop()
            try:
                node_class = await current.read_node_class()
            except Exception:
                continue

            if node_class == ua.NodeClass.Variable:
                variable_nodes.append(current)
                continue

            try:
                children = await current.get_children()
            except Exception:
                continue
            stack.extend(children)
        return variable_nodes

    async def _read_node_data_type(self, node: Node) -> str:
        """读取并规范化 OPC UA 节点数据类型。"""
        try:
            data_type = await node.read_data_type()
        except Exception:
            return "UNKNOWN"

        identifier = getattr(data_type, "Identifier", None)
        if identifier is None:
            return "UNKNOWN"
        return _normalize_opcua_data_type(str(identifier))


def _raw_datetime(value: object) -> datetime | None:
    """原样返回 datetime，非 datetime 返回 None"""
    if not isinstance(value, datetime):
        return None
    return value


def _node_id_to_string(node: Node) -> str:
    """将 Node 或 NodeId 统一转换为 node id 字符串。"""
    node_id = getattr(node, "nodeid", node)
    if hasattr(node_id, "to_string"):
        return str(node_id.to_string())
    return str(node_id)


def _extract_string_identifier(node_path: str) -> str:
    """从 ns=2;s=... 节点路径中提取字符串标识段。"""
    _, _, suffix = node_path.partition(";s=")
    return suffix or node_path


def _parse_logical_names(identifier: str) -> tuple[str, str, str]:
    """从 OPC UA 字符串标识解析 ld/ln/do 名称。"""
    parts = [part for part in identifier.split(".") if part]
    if len(parts) >= 4:
        return parts[-3], parts[-2], parts[-1]
    if len(parts) == 3:
        return parts[0], parts[1], parts[2]
    if len(parts) == 2:
        return "", parts[0], parts[1]
    if len(parts) == 1:
        return "", "", parts[0]
    return "", "", ""


def _normalize_opcua_data_type(identifier: str) -> str:
    """将 OPC UA BuiltinType Identifier 映射为稳定字符串类型。"""
    mapping = {
        "1": "BOOLEAN",
        "2": "INT8",
        "3": "UINT8",
        "4": "INT16",
        "5": "UINT16",
        "6": "INT32",
        "7": "UINT32",
        "8": "INT64",
        "9": "UINT64",
        "10": "FLOAT32",
        "11": "FLOAT64",
        "12": "STRING",
        "13": "DATETIME",
    }
    return mapping.get(identifier, "UNKNOWN")