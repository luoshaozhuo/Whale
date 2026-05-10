"""OPC UA acquisition adapter。

这个 adapter 只负责两件事：
- 把 ingest 侧请求 DTO 翻译成共享 reader 可识别的连接和节点参数
- 把共享 reader 返回的数据翻译回 ingest 侧 `AcquiredNodeState`

它不做：
- 周期控制
- 状态缓存写入
- diagnostics 记录
- 业务模式判断
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from whale.ingest.ports.source.source_acquisition_port import (
    SourceAcquisitionPort,
    SourceSubscriptionHandle,
    SubscriptionStateHandler,
)
from whale.ingest.usecases.dtos.acquired_node_state import AcquiredNodeState
from whale.ingest.usecases.dtos.source_acquisition_request import (
    AcquisitionExecutionOptions,
    AcquisitionItemData,
)
from whale.ingest.usecases.dtos.source_connection_data import SourceConnectionData
from whale.shared.source.source_reader import (
    OpcUaSourceReader,
    SourceConnectionProfile,
    SourceReadPoint,
)


@dataclass(slots=True)
class OpcUaAdapterSubscriptionHandle:
    """Adapter 层订阅句柄。

    这个句柄同时持有：
    - 已经连上的 reader
    - 底层 OPC UA subscription handle

    关闭顺序必须是：
    1. 先关 subscription
    2. 再退出 reader 上下文，断开 client
    """

    reader: OpcUaSourceReader
    subscription_handle: SourceSubscriptionHandle
    closed: bool = False

    async def close(self) -> None:
        if self.closed:
            return

        self.closed = True
        try:
            await self.subscription_handle.close()
        finally:
            await self.reader.__aexit__(None, None, None)


@dataclass(slots=True)
class _NoopSubscriptionHandle:
    """空点位订阅时返回的空句柄。"""

    closed: bool = False

    async def close(self) -> None:
        self.closed = True


class OpcUaSourceAcquisitionAdapter(SourceAcquisitionPort):
    """执行 OPC UA read / subscribe。"""

    async def read(
        self,
        execution: AcquisitionExecutionOptions,
        connection: SourceConnectionData,
        items: list[AcquisitionItemData],
    ) -> list[AcquiredNodeState]:
        observed_at = datetime.now(tz=UTC)
        node_paths = self._resolve_node_paths(connection, items)

        async with OpcUaSourceReader(
            self._build_connection_profile(execution, connection)
        ) as reader:
            values = await reader.read(node_paths, fast_mode=True)

        return [
            self._to_acquired_state_from_read_point(
                connection=connection,
                item=item,
                point=point,
                observed_at=observed_at,
            )
            for item, point in zip(items, values, strict=True)
        ]

    async def start_subscription(
        self,
        execution: AcquisitionExecutionOptions,
        connection: SourceConnectionData,
        items: list[AcquisitionItemData],
        *,
        state_received: SubscriptionStateHandler,
    ) -> SourceSubscriptionHandle:
        if not items:
            return _NoopSubscriptionHandle()

        reader = OpcUaSourceReader(self._build_connection_profile(execution, connection))
        await reader.__aenter__()

        node_paths = self._resolve_node_paths(connection, items)
        items_by_node_path = {
            node_path: item for item, node_path in zip(items, node_paths, strict=True)
        }

        async def _on_data_change(node: object, val: object, data: object) -> None:
            state = self._to_acquired_state_from_data_change(
                connection=connection,
                node=node,
                value=val,
                data=data,
                items_by_node_path=items_by_node_path,
            )
            if state is None:
                return

            await state_received([state])

        try:
            subscription_handle = await reader.start_subscription(
                node_paths,
                interval_ms=execution.interval_ms,
                on_data_change=_on_data_change,
            )
        except Exception:
            await reader.__aexit__(None, None, None)
            raise

        return OpcUaAdapterSubscriptionHandle(
            reader=reader,
            subscription_handle=subscription_handle,
        )

    @staticmethod
    def _resolve_node_paths(
        connection: SourceConnectionData,
        items: list[AcquisitionItemData],
    ) -> list[str]:
        namespace_uri = connection.namespace_uri.strip() if connection.namespace_uri else ""
        node_paths: list[str] = []

        for item in items:
            relative_path = item.relative_path.strip()
            if relative_path.startswith(("ns=", "nsu=")):
                node_paths.append(relative_path)
                continue

            if namespace_uri:
                node_paths.append(f"nsu={namespace_uri};s={relative_path}")
            else:
                node_paths.append(f"s={relative_path}")

        if not node_paths:
            raise ValueError("Cannot resolve OPC UA node paths.")

        return node_paths

    @staticmethod
    def _resolve_node_ids(
        connection: SourceConnectionData,
        items: list[AcquisitionItemData],
    ) -> list[str]:
        """兼容旧测试中的命名。

        对 OPC UA 来说，这里返回的其实是可直接传给 client.get_node(...)
        的节点路径表达式，因此统一复用 `_resolve_node_paths()`。
        """

        return OpcUaSourceAcquisitionAdapter._resolve_node_paths(connection, items)

    @staticmethod
    def _build_connection_profile(
        execution: AcquisitionExecutionOptions,
        connection: SourceConnectionData,
    ) -> SourceConnectionProfile:
        endpoint = _build_endpoint(execution, connection)
        if not endpoint:
            raise ValueError("Cannot resolve OPC UA endpoint.")

        return SourceConnectionProfile(
            endpoint=endpoint,
            namespace_uri=_resolve_namespace_uri(connection),
            timeout_seconds=execution.request_timeout_ms / 1000,
            params={
                "subscription_notification_queue_size": (
                    execution.subscription_notification_queue_size
                ),
                "subscription_notification_worker_count": (
                    execution.subscription_notification_worker_count
                ),
                "subscription_notification_max_lag_ms": (
                    execution.subscription_notification_max_lag_ms
                ),
            },
        )

    @staticmethod
    def _to_acquired_state_from_read_point(
        *,
        connection: SourceConnectionData,
        item: AcquisitionItemData,
        point: SourceReadPoint,
        observed_at: datetime,
    ) -> AcquiredNodeState:
        return AcquiredNodeState(
            source_id=_resolve_source_id(connection),
            node_key=item.key,
            value=str(point.value),
            observed_at=point.source_timestamp or observed_at,
        )

    @staticmethod
    def _to_acquired_state_from_data_change(
        *,
        connection: SourceConnectionData,
        node: object,
        value: object,
        data: object,
        items_by_node_path: dict[str, AcquisitionItemData],
    ) -> AcquiredNodeState | None:
        node_path = _resolve_node_path(node)
        item = items_by_node_path.get(node_path)
        if item is None:
            return None

        return AcquiredNodeState(
            source_id=_resolve_source_id(connection),
            node_key=item.key,
            value=str(value),
            observed_at=_resolve_observed_at(data),
        )


def _resolve_namespace_uri(connection: SourceConnectionData) -> str | None:
    if connection.namespace_uri.strip():
        return connection.namespace_uri.strip()
    return None


def _build_endpoint(
    execution: AcquisitionExecutionOptions,
    connection: SourceConnectionData,
) -> str:
    protocol = execution.protocol.strip().lower()
    transport = execution.transport.strip().lower()
    host = connection.host.strip()
    port = connection.port

    if not protocol or not transport or not host:
        return ""

    return f"{protocol}.{transport}://{host}:{port}"


def _resolve_source_id(connection: SourceConnectionData) -> str:
    if connection.ld_name.strip():
        return connection.ld_name.strip()
    if connection.ied_name.strip():
        return connection.ied_name.strip()
    return "unknown_source"


def _resolve_node_path(node: object) -> str:
    node_id = getattr(node, "nodeid", node)
    if hasattr(node_id, "to_string"):
        return str(node_id.to_string())
    return str(node_id)


def _resolve_observed_at(data: object) -> datetime:
    monitored_item = getattr(data, "monitored_item", None)
    value = getattr(monitored_item, "Value", None)
    source_timestamp = getattr(value, "SourceTimestamp", None)
    if isinstance(source_timestamp, datetime):
        if source_timestamp.tzinfo is None:
            return source_timestamp.replace(tzinfo=UTC)
        return source_timestamp.astimezone(UTC)

    return datetime.now(tz=UTC)