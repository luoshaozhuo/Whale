"""tools 侧 OPC UA reader 兼容包装。

主实现已经迁到 `whale.shared.source.source_reader`。
这个文件保留的目的只有两个：
- 兼容 tools 侧现有 import 路径
- 把 shared 层返回的通用模型转换回 tools 侧领域模型
"""

from __future__ import annotations

from collections.abc import Sequence

from whale.shared.source.source_reader import (
    OpcUaSourceReader as SharedOpcUaSourceReader,
    SourceConnectionProfile,
)
from tools.source_simulation.domain import (
    SourceConnection,
    SourceNodeInfo,
    SourceReadPoint,
)


class OpcUaSourceReader(SharedOpcUaSourceReader):
    """tools 侧兼容 reader。

    继承 shared 主实现，只负责：
    - 把 tools 侧 `SourceConnection` 转成共享连接 profile
    - 把 shared 返回模型转换回 tools 侧 dataclass
    """

    def __init__(self, connection: SourceConnection) -> None:
        self._tools_connection = connection
        super().__init__(self._build_connection_profile(connection))

    @property
    def connection(self) -> SourceConnection:
        return self._tools_connection

    async def read(
        self,
        node_paths: Sequence[str],
        *,
        fast_mode: bool = True,
    ) -> tuple[SourceReadPoint, ...]:
        batch = await super().read(node_paths, fast_mode=fast_mode)
        return tuple(
            SourceReadPoint(
                path=point.path,
                value=point.value,
                status=point.status,
                source_timestamp=point.source_timestamp,
                server_timestamp=point.server_timestamp,
            )
            for point in batch
        )

    async def list_nodes(self) -> tuple[SourceNodeInfo, ...]:
        nodes = await super().list_nodes()
        return tuple(
            SourceNodeInfo(
                node_path=node.node_path,
                data_type=node.data_type,
                ld_name=node.ld_name,
                ln_name=node.ln_name,
                do_name=node.do_name,
            )
            for node in nodes
        )

    @staticmethod
    def _build_connection_profile(connection: SourceConnection) -> SourceConnectionProfile:
        transport = connection.transport.strip().lower()
        return SourceConnectionProfile(
            endpoint=f"opc.{transport}://{connection.host}:{connection.port}",
            namespace_uri=connection.namespace_uri,
            timeout_seconds=connection.timeouts.request_timeout_seconds or 4.0,
            params=dict(connection.params),
        )
