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
from typing import Any, Dict, List, Literal

from asyncua import Client, Node, ua  # type: ignore[import-untyped]
from whale.shared.source.models import (
    Batch,
    NodeValueChange,
    SourceConnectionProfile,
    SourceNodeInfo,
    SubscriptionCallback,
)
from whale.shared.source.ports import SourceReaderPort, SourceSubscriptionHandlePort
from whale.shared.source.opcua.backends import (
    AsyncuaPreparedReadPlan,
    PreparedReadPlan,
    RawOpcUaReadResult,
)
from whale.shared.source.opcua.backends.asyncua_backend import AsyncuaOpcUaClientBackend
from whale.shared.source.opcua.backends.factory import build_opcua_client_backend
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
        self._backend = build_opcua_client_backend(connection)
        self._subscriptions: List[OpcUaSubscriptionHandle] = []

    @property
    def endpoint(self) -> str:
        return self._connection.endpoint

    @property
    def _client(self) -> Client | None:
        """Compatibility proxy for tests that patch the underlying asyncua client."""

        if isinstance(self._backend, AsyncuaOpcUaClientBackend):
            return getattr(self._backend, "_client", None)
        return None

    @_client.setter
    def _client(self, value: Client | None) -> None:
        """Compatibility proxy for tests that patch the underlying asyncua client."""

        backend = self._asyncua_backend_or_raise()
        backend._client = value  # type: ignore[attr-defined]

    @property
    def _nsidx(self) -> int | None:
        """Compatibility proxy for tests that patch namespace index directly."""

        if isinstance(self._backend, AsyncuaOpcUaClientBackend):
            return getattr(self._backend, "_nsidx", None)
        return None

    @_nsidx.setter
    def _nsidx(self, value: int | None) -> None:
        """Compatibility proxy for tests that patch namespace index directly."""

        backend = self._asyncua_backend_or_raise()
        backend._nsidx = value  # type: ignore[attr-defined]

    async def __aenter__(self) -> "OpcUaSourceReader":
        """异步上下文进入，建立 OPC UA 会话."""
        await self._backend.connect()
        return self

    async def __aexit__(self, exc_type: object, exc: object, tb: object) -> None:
        """异步上下文退出，关闭订阅并断开连接."""
        for sub in self._subscriptions:
            await sub.close()
        try:
            await self._backend.disconnect()
        finally:
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
        plan = self.prepare_read(addresses)
        return await self.read_prepared(plan, mode=mode)

    def prepare_read(self, addresses: Sequence[str]) -> PreparedReadPlan:
        """Prepare a reusable full-read plan without issuing any network request."""
        return self._backend.prepare_read(addresses)

    async def read_prepared(
        self,
        plan: PreparedReadPlan,
        *,
        mode: Literal["full", "value_only"] = "full",
    ) -> Batch:
        """Read with a pre-built plan to avoid hot-path normalization and cache lookup."""
        if mode == "value_only":
            self._value_only_backend_or_raise()
            return await self._read_prepared_values(plan)

        self._full_batch_backend_or_raise()

        raw_result = await self.read_prepared_raw(plan)
        if not raw_result.ok:
            return self._build_error_batch(
                reason=raw_result.error_reason or "read_failed",
                exception=raw_result.exception,
                retry_count=raw_result.retry_count,
            )

        return self._build_full_batch(
            plan,
            raw_result.data_values,
            response_timestamp=raw_result.response_timestamp,
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
        self._subscription_backend_or_raise()
        client = self._client_or_raise()
        plan = self.prepare_read(addresses)
        if not isinstance(plan, AsyncuaPreparedReadPlan):
            raise NotImplementedError(
                "subscription currently requires asyncua prepared nodes"
            )
        nodes = plan.nodes

        # Initial baseline read before handing over to subscription-driven updates.
        try:
            batch = await self.read_prepared(plan, mode="full")
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

        handler = OpcUaSubscriptionHandler(
            on_data_change,
            reader=self,
            subscription_node_count=len(addresses),
            addresses=addresses,
        )
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
        self._browse_backend_or_raise()
        _ = self._client_or_raise()
        nsidx = self._backend.namespace_index
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
    def _asyncua_backend_or_raise(self) -> AsyncuaOpcUaClientBackend:
        """Return asyncua backend for operations not yet abstracted from it."""

        if not isinstance(self._backend, AsyncuaOpcUaClientBackend):
            raise NotImplementedError(
                "This operation currently requires asyncua OPC UA client backend"
            )
        return self._backend

    def _full_batch_backend_or_raise(self) -> AsyncuaOpcUaClientBackend:
        """Require asyncua backend for full Batch construction."""

        if not isinstance(self._backend, AsyncuaOpcUaClientBackend):
            raise NotImplementedError(
                "full Batch read requires asyncua backend because open62541 raw polling "
                "does not expose full DataValue metadata yet"
            )
        return self._backend

    def _value_only_backend_or_raise(self) -> AsyncuaOpcUaClientBackend:
        """Require backend values for value-only Batch construction."""

        if not isinstance(self._backend, AsyncuaOpcUaClientBackend):
            raise NotImplementedError(
                "value_only Batch read requires backend values; open62541 runner "
                "currently returns count-only raw results"
            )
        return self._backend

    def _subscription_backend_or_raise(self) -> AsyncuaOpcUaClientBackend:
        """Require asyncua backend for subscription APIs."""

        if not isinstance(self._backend, AsyncuaOpcUaClientBackend):
            raise NotImplementedError(
                "subscription currently requires asyncua client subscription API"
            )
        return self._backend

    def _browse_backend_or_raise(self) -> AsyncuaOpcUaClientBackend:
        """Require asyncua backend for browse/list-nodes APIs."""

        if not isinstance(self._backend, AsyncuaOpcUaClientBackend):
            raise NotImplementedError(
                "browse currently requires asyncua node browsing API"
            )
        return self._backend

    def _client_or_raise(self) -> Client:
        """获取已连接 OPC UA client，未连接则抛出异常."""
        return self._asyncua_backend_or_raise().client

    async def _read_prepared_values(self, plan: PreparedReadPlan) -> Batch:
        """Read prepared nodes via value_only path with the same retry semantics."""
        if not isinstance(plan, AsyncuaPreparedReadPlan):
            raise TypeError("value_only read requires AsyncuaPreparedReadPlan")
        client = self._client_or_raise()
        retry_count = 0
        max_retries = 1

        while retry_count <= max_retries:
            try:
                values = await asyncio.wait_for(
                    client.read_values(plan.nodes),
                    timeout=self._connection.timeout_seconds,
                )
                changes = tuple(
                    NodeValueChange(
                        node_key=node_path,
                        value=value,
                        quality=None,
                        source_timestamp=None,
                        server_timestamp=None,
                        client_sequence=0,
                        attributes={"value_only": True},
                    )
                    for node_path, value in zip(plan.node_paths, values)
                )
                return self._build_batch(
                    changes=changes,
                    availability_status="VALID",
                    attributes={},
                )
            except (asyncio.TimeoutError, Exception) as ex:
                retry_count += 1
                if retry_count > max_retries:
                    return self._build_error_batch(
                        reason="timeout" if isinstance(ex, asyncio.TimeoutError) else "read_failed",
                        exception=str(ex),
                        retry_count=retry_count,
                    )
                await asyncio.sleep(0.05)  # 短暂退避

        return self._build_error_batch(reason="read_failed", retry_count=max_retries + 1)

    async def read_prepared_raw(
        self,
        plan: PreparedReadPlan,
    ) -> RawOpcUaReadResult:
        """Read prepared DataValues without constructing Batch or NodeValueChange."""
        return await self._backend.read_prepared_raw(plan)

    def _build_full_batch(
        self,
        plan: PreparedReadPlan,
        data_values: Sequence[object],
        *,
        response_timestamp: datetime | None,
    ) -> Batch:
        """Build a full Batch from prepared plan metadata and raw DataValues."""
        changes: list[NodeValueChange] = []
        for node_path, data_value in zip(plan.node_paths, data_values):
            if not all(
                hasattr(data_value, attribute)
                for attribute in (
                    "Value",
                    "StatusCode",
                    "SourceTimestamp",
                    "ServerTimestamp",
                )
            ):
                raise TypeError(
                    "full Batch read requires asyncua DataValue metadata"
                )

            data_value_obj = data_value
            value_wrapper = getattr(data_value_obj, "Value")
            changes.append(
                NodeValueChange(
                    node_key=node_path,
                    value=value_wrapper.Value if value_wrapper else None,
                    quality=(
                        str(getattr(data_value_obj, "StatusCode"))
                        if getattr(data_value_obj, "StatusCode")
                        else None
                    ),
                    source_timestamp=_raw_datetime(
                        getattr(data_value_obj, "SourceTimestamp")
                    ),
                    server_timestamp=_raw_datetime(
                        getattr(data_value_obj, "ServerTimestamp")
                    ),
                    client_sequence=0,
                    attributes={},
                )
            )
        return self._build_batch(
            changes=tuple(changes),
            availability_status="VALID",
            attributes={
                "response_timestamp": response_timestamp,
            },
        )

    def _build_error_batch(
        self,
        *,
        reason: str,
        exception: str | None = None,
        retry_count: int,
    ) -> Batch:
        """Build a uniform error Batch for read failures."""
        attributes: Dict[str, Any] = {
            "reason": reason,
            "retry_count": retry_count,
        }
        if exception is not None:
            attributes["exception"] = exception
        return self._build_batch(
            changes=(),
            availability_status="ERROR",
            attributes=attributes,
        )

    def _build_batch(
        self,
        *,
        changes: tuple[NodeValueChange, ...],
        availability_status: str,
        attributes: Dict[str, Any],
    ) -> Batch:
        """Build a Batch with consistent timestamps."""
        now = datetime.now(tz=timezone.utc)
        return Batch(
            changes=changes,
            batch_observed_at=now,
            client_received_at=now,
            availability_status=availability_status,
            attributes=attributes,
        )

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
