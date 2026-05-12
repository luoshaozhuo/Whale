"""OPC UA acquisition adapter。

本模块是 ingest usecase 与共享 OPC UA reader 之间的适配层。

设计约定：
- adapter 只负责 DTO 转换，不做周期控制、不写 cache、不做 diagnostics；
- read() 将一次 OPC UA 批量读取结果转换为 AcquiredNodeStateBatch；
- start_subscription() 启动 reader 订阅，并将 SourceDataChangeBatch 转换为 AcquiredNodeStateBatch；
- reader 只识别协议层 path，adapter 负责 path -> AcquisitionItemData.node_key 的映射；
- batch 级时间作为 LD 状态视图的统一时间；
- value 级 source/server timestamp 只作为乱序保护和诊断信息；
- subscription initial read baseline 不在 adapter 内做，由 SubscriptionAcquisitionRole 编排。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime

from whale.ingest.ports.source.source_acquisition_port import (
    SourceAcquisitionPort,
    SourceSubscriptionHandle,
    SubscriptionStateHandler,
)
from whale.ingest.usecases.dtos.acquired_node_state import (
    AcquiredNodeStateBatch,
    AcquiredNodeValue,
)
from whale.ingest.usecases.dtos.source_acquisition_request import (
    AcquisitionExecutionOptions,
    AcquisitionItemData,
)
from whale.ingest.usecases.dtos.source_connection_data import SourceConnectionData
from whale.shared.source.models import (
    SourceConnectionProfile,
    SourceDataChangeBatch,
    SourceReadPoint,
)
from whale.shared.source.opcua.reader import OpcUaSourceReader
from whale.shared.source.ports import SourceReaderPort


@dataclass(slots=True)
class OpcUaAdapterSubscriptionHandle:
    """Adapter 层订阅句柄。

    这个句柄同时持有：
    - 已经连上的 reader；
    - 底层 OPC UA subscription handle。

    关闭顺序必须是：
    1. 先关闭 subscription；
    2. 再退出 reader 上下文，断开 client。
    """

    reader: SourceReaderPort
    subscription_handle: SourceSubscriptionHandle
    closed: bool = False

    async def close(self) -> None:
        """关闭订阅和 reader 连接。"""

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
        """关闭空句柄。"""

        self.closed = True


class OpcUaSourceAcquisitionAdapter(SourceAcquisitionPort):
    """执行 OPC UA read / subscribe。"""

    async def read(
        self,
        execution: AcquisitionExecutionOptions,
        connection: SourceConnectionData,
        items: list[AcquisitionItemData],
    ) -> AcquiredNodeStateBatch:
        """执行一次 OPC UA 批量读取，并返回 batch。"""

        client_received_at = datetime.now(tz=UTC)
        node_paths = self._resolve_node_paths(connection, items)

        async with self._build_reader(execution, connection) as reader:
            points = await reader.read(node_paths, include_metadata=True)

        client_processed_at = datetime.now(tz=UTC)

        return self._to_acquired_batch_from_read_points(
            connection=connection,
            items=items,
            points=list(points),
            client_received_at=client_received_at,
            client_processed_at=client_processed_at,
        )

    async def start_subscription(
        self,
        execution: AcquisitionExecutionOptions,
        connection: SourceConnectionData,
        items: list[AcquisitionItemData],
        *,
        state_received: SubscriptionStateHandler,
    ) -> SourceSubscriptionHandle:
        """启动 OPC UA 订阅，并将 reader 微批次转换为 ingest batch。"""

        if not items:
            return _NoopSubscriptionHandle()

        reader = self._build_reader(execution, connection)
        await reader.__aenter__()

        node_paths = self._resolve_node_paths(connection, items)
        item_resolver = _NodeItemResolver(
            node_paths=node_paths,
            items=items,
        )

        async def _on_data_change(batch: SourceDataChangeBatch) -> None:
            acquired_batch = self._to_acquired_batch_from_data_change_batch(
                connection=connection,
                item_resolver=item_resolver,
                batch=batch,
            )

            if acquired_batch.is_empty():
                return

            await state_received(acquired_batch)

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
        """将业务点位 relative_path 转换为 OPC UA node path。"""

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
    def _build_connection_profile(
        execution: AcquisitionExecutionOptions,
        connection: SourceConnectionData,
    ) -> SourceConnectionProfile:
        """构造共享 reader 使用的连接 profile。"""

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
            },
        )

    @classmethod
    def _build_reader(
        cls,
        execution: AcquisitionExecutionOptions,
        connection: SourceConnectionData,
    ) -> SourceReaderPort:
        """构造一个满足通用 source reader port 的具体实现。"""

        return OpcUaSourceReader(cls._build_connection_profile(execution, connection))

    @staticmethod
    def _to_acquired_batch_from_read_points(
        *,
        connection: SourceConnectionData,
        items: list[AcquisitionItemData],
        points: list[SourceReadPoint],
        client_received_at: datetime,
        client_processed_at: datetime,
    ) -> AcquiredNodeStateBatch:
        """将一次 read 结果转换为 AcquiredNodeStateBatch。"""

        values = [
            AcquiredNodeValue(
                node_key=item.key,
                value=str(point.value),
                quality=point.status,
                source_timestamp=point.source_timestamp,
                server_timestamp=point.server_timestamp,
                client_sequence=None,
            )
            for item, point in zip(items, points, strict=True)
        ]

        return AcquiredNodeStateBatch(
            source_id=_resolve_source_id(connection),
            batch_observed_at=client_received_at,
            client_received_at=client_received_at,
            client_processed_at=client_processed_at,
            values=values,
            availability_status="VALID",
            attributes={
                "acquisition_kind": "read",
            },
        )

    @staticmethod
    def _to_acquired_batch_from_data_change_batch(
        *,
        connection: SourceConnectionData,
        item_resolver: "_NodeItemResolver",
        batch: SourceDataChangeBatch,
    ) -> AcquiredNodeStateBatch:
        """将 reader 的 SourceDataChangeBatch 转换为 AcquiredNodeStateBatch。"""

        values: list[AcquiredNodeValue] = []

        for change in batch.changes:
            item = item_resolver.resolve(change.path)
            if item is None:
                continue

            values.append(
                AcquiredNodeValue(
                    node_key=item.key,
                    value=str(change.value),
                    quality=change.status,
                    source_timestamp=change.source_timestamp,
                    server_timestamp=change.server_timestamp,
                    client_sequence=change.client_sequence,
                )
            )

        return AcquiredNodeStateBatch(
            source_id=_resolve_source_id(connection),
            batch_observed_at=batch.client_received_at,
            client_received_at=batch.client_received_at,
            client_processed_at=batch.client_processed_at,
            values=values,
            availability_status="VALID",
            attributes={
                "acquisition_kind": "subscription_datachange",
            },
        )


@dataclass(slots=True)
class _NodeItemResolver:
    """OPC UA node path 到 AcquisitionItemData 的解析器。

    asyncua 回调中的 nodeid 字符串可能与订阅时传入的 node path 不完全一致：
    - 订阅时可能是 nsu=xxx;s=AAA.BBB；
    - 回调时可能是 ns=2;s=AAA.BBB。

    因此这里同时支持：
    - 完整 node path 匹配；
    - ;s= 后逻辑路径匹配；
    - item.relative_path 匹配。
    """

    node_paths: list[str]
    items: list[AcquisitionItemData]
    _items_by_full_path: dict[str, AcquisitionItemData] = field(
        init=False,
        default_factory=dict,
    )
    _items_by_logical_path: dict[str, AcquisitionItemData] = field(
        init=False,
        default_factory=dict,
    )

    def __post_init__(self) -> None:
        for node_path, item in zip(self.node_paths, self.items, strict=True):
            self._items_by_full_path[node_path] = item

            logical_path = _resolve_logical_path(node_path)
            if logical_path:
                self._items_by_logical_path[logical_path] = item

            relative_path = item.relative_path.strip()
            if relative_path:
                self._items_by_logical_path[relative_path] = item

    def resolve(self, node_path: str) -> AcquisitionItemData | None:
        """解析一个 OPC UA node path 对应的采集点位。"""

        item = self._items_by_full_path.get(node_path)
        if item is not None:
            return item

        logical_path = _resolve_logical_path(node_path)
        if logical_path:
            return self._items_by_logical_path.get(logical_path)

        return None


def _resolve_namespace_uri(connection: SourceConnectionData) -> str | None:
    """解析 namespace_uri。"""

    if connection.namespace_uri.strip():
        return connection.namespace_uri.strip()
    return None


def _build_endpoint(
    execution: AcquisitionExecutionOptions,
    connection: SourceConnectionData,
) -> str:
    """构造 OPC UA endpoint。"""

    protocol = execution.protocol.strip().lower()
    transport = execution.transport.strip().lower()
    host = connection.host.strip()
    port = connection.port

    if not protocol or not transport or not host:
        return ""

    return f"{protocol}.{transport}://{host}:{port}"


def _resolve_source_id(connection: SourceConnectionData) -> str:
    """解析 source_id。"""

    if connection.ld_name.strip():
        return connection.ld_name.strip()
    if connection.ied_name.strip():
        return connection.ied_name.strip()
    return "unknown_source"


def _resolve_logical_path(node_path: str) -> str | None:
    """从 OPC UA node path 中提取 ;s= 后的逻辑路径。"""

    if ";s=" not in node_path:
        return None

    return node_path.split(";s=", maxsplit=1)[1].strip() or None
