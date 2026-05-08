"""OPC UA adapter that implements the source-simulator contract.

本模块负责：
1. 生成 NodeSet XML；
2. 导入 XML 创建 OPC UA 地址空间；
3. 启动 OPC UA Server；
4. 建立点位写入索引；
5. 对外提供 writes(...)，用于后续周期更新点位值。

地址空间结构由 nodeset_builder.py 负责。
本模块不再手动 add_object / add_variable。
"""

from __future__ import annotations

import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol, cast

from asyncua import ua  # type: ignore[import-untyped]
from asyncua.sync import Server  # type: ignore[import-untyped]

from tools.source_simulation.adapters.opcua.nodeset_builder import (
    build_nodeset_xml,
    logical_path,
    opcua_data_type,
)
from tools.source_simulation.domain import SimulatedPoint, SimulatedSource


class OpcUaSourceSimulatorError(ValueError):
    """当 OPC UA 仿真器启动参数非法时抛出。"""


class _VariableNode(Protocol):
    def write_value(self, value: object) -> object: ...

    def set_writable(self) -> object: ...


class OpcUaSourceSimulator:
    """OPC UA 仿真源适配器。

    一个 OpcUaSourceSimulator 对应一个 SimulatedSource。
    """

    def __init__(
        self,
        source: SimulatedSource,
    ) -> None:
        normalized_protocol = (
            source.connection.protocol.strip().lower().replace("_", "").replace("-", "")
        )
        if normalized_protocol != "opcua":
            raise OpcUaSourceSimulatorError("OpcUaSourceSimulator only supports `opcua` sources")

        namespace_uri = str(source.connection.namespace_uri or "").strip()
        if not namespace_uri:
            raise OpcUaSourceSimulatorError(
                "OPC UA source simulator requires connection.namespace_uri"
            )

        if not source.connection.ied_name.strip():
            raise OpcUaSourceSimulatorError("OPC UA source simulator requires connection.ied_name")

        if not source.connection.ld_name.strip():
            raise OpcUaSourceSimulatorError("OPC UA source simulator requires connection.ld_name")

        self._source = source
        self._namespace_uri = namespace_uri
        self._server: Server | None = None
        self._temp_dir: tempfile.TemporaryDirectory[str] | None = None

        # 写入目标索引：
        # key -> (OPC UA variable node, SimulatedPoint)
        #
        # 支持两种写入 key：
        # 1. point.key
        #    例如："WPPD1.DevSt"
        # 2. full logical path
        #    例如："IED001.LD0.WPPD1.DevSt"
        self._write_targets_by_key: dict[str, tuple[_VariableNode, SimulatedPoint]] = {}

    @property
    def endpoint(self) -> str:
        """返回 OPC UA Server endpoint。"""

        return self._build_endpoint()

    @property
    def name(self) -> str:
        """返回仿真源名称。"""

        return self._source.connection.name

    def start(self) -> "OpcUaSourceSimulator":
        """启动 OPC UA Server。"""

        if self._server is not None:
            return self

        nodeset_path = self._build_nodeset_file()

        server = Server()
        server.set_endpoint(self._build_endpoint())
        self._apply_security(server)

        # 导入 XML，创建地址空间。
        # XML 中已经包含变量初始值，因此这里不再额外写 initial_value。
        server.import_xml(path=str(nodeset_path))

        server.start()
        self._server = server

        variable_specs = self._build_variable_specs(server)

        self._write_targets_by_key = {}

        for node, point in variable_specs:
            full_path = logical_path(self._source.connection, point)
            target = (node, point)

            self._write_targets_by_key[point.key] = target
            self._write_targets_by_key[full_path] = target

        return self

    def stop(self) -> None:
        """停止 OPC UA Server，并清理临时 XML 文件。"""

        if self._server is None:
            return

        self._server.stop()
        self._server = None
        self._write_targets_by_key = {}

        if self._temp_dir is not None:
            self._temp_dir.cleanup()
            self._temp_dir = None

    def __enter__(self) -> "OpcUaSourceSimulator":
        return self.start()

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        self.stop()

    def writes(self, values_by_key: dict[str, str | int | float | bool]) -> None:
        """批量写入仿真点位值。

        values_by_key 示例：

        {
            "WPPD1.DevSt": 1.0,
            "IED001.LD0.WPPD1.Gra": 23.5,
        }

        这里写入的是 ua.DataValue，
        因此 client 通过 read_attributes(..., Value) 可以拿到：
        - value
        - status
        - source_timestamp
        - server_timestamp
        """

        if self._server is None:
            raise RuntimeError("Simulator runtime must be started before writes()")

        batch_timestamp = datetime.now(tz=UTC)

        for key, value in values_by_key.items():
            target = self._write_targets_by_key.get(key)
            if target is None:
                continue

            node, point = target

            try:
                node.write_value(self._build_data_value_from_value(point, value, batch_timestamp))
            except Exception:
                # 单点写入失败，不影响其他点位。
                continue

    def _build_nodeset_file(self) -> Path:
        """生成临时 NodeSet XML 文件。"""

        self._temp_dir = tempfile.TemporaryDirectory(prefix="opcua_source_sim_")
        nodeset_path = Path(self._temp_dir.name) / f"{self.name}.nodeset.xml"

        nodeset_path.write_text(
            build_nodeset_xml(
                points=self._source.points,
                connection=self._source.connection,
                namespace_uri=self._namespace_uri,
            ),
            encoding="utf-8",
        )

        return nodeset_path

    def _apply_security(self, server: Server) -> None:
        """根据 SourceConnection.security 配置 OPC UA 安全策略。"""

        security_policy = self._source.connection.security.policy
        security_mode = self._source.connection.security.mode

        if (
            self._source.connection.security.enabled
            and security_policy
            and security_mode
            and security_policy != "None"
            and security_mode != "None"
        ):
            try:
                server.set_security_policy(
                    [
                        ua.SecurityPolicyType[security_policy],
                        ua.MessageSecurityMode[security_mode],
                    ]
                )
            except (KeyError, AttributeError):
                pass

    def _build_endpoint(self) -> str:
        """根据 connection 生成 OPC UA endpoint。"""

        transport = self._source.connection.transport.strip().lower()
        scheme = "opc.tcp" if transport == "tcp" else f"opc.{transport}"
        return f"{scheme}://{self._source.connection.host}:{self._source.connection.port}"

    def _build_variable_specs(
        self,
        server: Server,
    ) -> tuple[tuple[_VariableNode, SimulatedPoint], ...]:
        """根据 IED.LD.LN.DO 逻辑路径获取 XML 创建出来的变量节点。"""

        namespace_index = server.get_namespace_index(self._namespace_uri)

        specs: list[tuple[_VariableNode, SimulatedPoint]] = []

        for point in self._source.points:
            full_path = logical_path(self._source.connection, point)
            node = cast(_VariableNode, server.get_node(f"ns={namespace_index};s={full_path}"))

            try:
                node.set_writable()
            except Exception:
                pass

            specs.append((node, point))

        return tuple(specs)

    def _build_data_value_from_value(
        self,
        point: SimulatedPoint,
        value: str | int | float | bool | None,
        timestamp: datetime | None = None,
    ) -> ua.DataValue:
        """根据点位定义和值构造 OPC UA DataValue。"""

        now = timestamp or datetime.now(tz=UTC)

        return ua.DataValue(
            Value=self._build_variant_from_value(point, value),
            StatusCode_=ua.StatusCode(ua.StatusCodes.Good),
            SourceTimestamp=now,
            ServerTimestamp=now,
        )

    def _build_variant_from_value(
        self,
        point: SimulatedPoint,
        value: str | int | float | bool | None,
    ) -> ua.Variant:
        """根据点位数据类型构造 OPC UA Variant。"""

        return ua.Variant(
            self._cast_value(point, value),
            self._variant_type_from_point(point),
        )

    def _variant_type_from_point(self, point: SimulatedPoint) -> ua.VariantType:
        """根据 SimulatedPoint.data_type 推断 OPC UA VariantType。"""

        opcua_type_name = opcua_data_type(point.data_type)

        if opcua_type_name == "Boolean":
            return ua.VariantType.Boolean

        if opcua_type_name == "Int32":
            return ua.VariantType.Int32

        if opcua_type_name == "String":
            return ua.VariantType.String

        return ua.VariantType.Double

    def _cast_value(
        self,
        point: SimulatedPoint,
        value: str | int | float | bool | None,
    ) -> str | int | float | bool:
        """把外部传入值转换为 OPC UA 变量所需的 Python 值类型。"""

        opcua_type_name = opcua_data_type(point.data_type)

        if opcua_type_name == "Boolean":
            return bool(value)

        if opcua_type_name == "Int32":
            casted = int(float(value or 0))
            return max(-2147483648, min(2147483647, casted))

        if opcua_type_name == "String":
            return str(value or "")

        return float(value or 0.0)
