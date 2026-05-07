"""根据协议无关的仿真点位定义，生成 OPC UA NodeSet XML。

本模块只负责“建模”：
- 根据 SourceConnection 中的 ied_name / ld_name；
- 根据 SimulatedPoint 中的 ln_name / do_name；
- 生成符合 OPC UA NodeSet 结构的 XML。

最终生成的地址空间层级为：

Objects
  └── WindFarm
        └── {IED}
              └── {LD}
                    └── {LN}
                          └── {DO}

变量节点的 NodeId 采用稳定的逻辑路径：

ns=1;s={IED}.{LD}.{LN}.{DO}

注意：
WindFarm 只是 browse 层级中的业务容器，不放进变量 NodeId。
"""

from __future__ import annotations

from datetime import UTC, datetime
from xml.sax.saxutils import escape

from tools.source_simulation.domain import SimulatedPoint, SourceConnection


# 将系统内部的数据类型映射为 OPC UA NodeSet XML 可识别的数据类型。
# 当前只保留最常用的标量类型，避免仿真模型过度复杂。
_SCADA_TO_OPCUA_TYPE: dict[str, str] = {
    "FLOAT64": "Double",
    "FLOAT32": "Double",
    "DOUBLE": "Double",
    "FLOAT": "Double",
    "INT8": "Int32",
    "INT16": "Int32",
    "INT32": "Int32",
    "INT64": "Int32",
    "INT8U": "Int32",
    "INT16U": "Int32",
    "INT32U": "Int32",
    "UINT8": "Int32",
    "UINT16": "Int32",
    "UINT32": "Int32",
    "BOOLEAN": "Boolean",
    "BOOL": "Boolean",
    "VISSTRING255": "String",
    "STRING": "String",
    "CODED_ENUM": "Int32",
    "TIMESTAMP": "String",
    "DATETIME": "String",
    "OCTET_STRING": "String",
}


# NodeSet XML 头部：
# 1. 声明命名空间；
# 2. 注册标准 OPC UA namespace 和业务 namespace；
# 3. 定义后续 XML 中要用到的别名；
# 4. 创建 WindFarm 业务根对象。
_HEADER = """<?xml version="1.0" encoding="utf-8"?>
<UANodeSet xmlns="http://opcfoundation.org/UA/2011/03/UANodeSet.xsd"
           LastModified="{last_modified}">
  <NamespaceUris>
    <Uri>http://opcfoundation.org/UA/</Uri>
    <Uri>{namespace_uri}</Uri>
  </NamespaceUris>
  <Aliases>
    <Alias Alias="BaseObjectType">i=58</Alias>
    <Alias Alias="FolderType">i=61</Alias>
    <Alias Alias="BaseDataVariableType">i=63</Alias>
    <Alias Alias="ObjectsFolder">i=85</Alias>
    <Alias Alias="HasTypeDefinition">i=40</Alias>
    <Alias Alias="Organizes">i=35</Alias>
    <Alias Alias="HasComponent">i=47</Alias>
    <Alias Alias="Double">i=11</Alias>
    <Alias Alias="Int32">i=6</Alias>
    <Alias Alias="Boolean">i=1</Alias>
    <Alias Alias="String">i=12</Alias>
  </Aliases>

  <UAObject NodeId="ns=1;s=WindFarm" BrowseName="1:WindFarm">
    <DisplayName>WindFarm</DisplayName>
    <References>
      <Reference ReferenceType="Organizes" IsForward="false">ObjectsFolder</Reference>
      <Reference ReferenceType="HasTypeDefinition">FolderType</Reference>
    </References>
  </UAObject>
"""


# 普通对象模板，用于创建 LD、LN 等层级节点。
#
# 例如：
# IED001.LD0
# IED001.LD0.WPPD1
#
# ParentNodeId 用来表达 browse 层级关系。
_OBJECT_TEMPLATE = """  <UAObject NodeId="ns=1;s={node_id}"
            BrowseName="1:{browse_name}"
            ParentNodeId="ns=1;s={parent_node_id}">
    <DisplayName>{display_name}</DisplayName>
    <References>
      <Reference ReferenceType="HasTypeDefinition">BaseObjectType</Reference>
      <Reference ReferenceType="HasComponent" IsForward="false">ns=1;s={parent_node_id}</Reference>
    </References>
  </UAObject>
"""


# IED 对象模板。
#
# IED 是 WindFarm 下的一级业务对象：
#
# Objects
#   └── WindFarm
#         └── IED001
_IED_OBJECT_TEMPLATE = """  <UAObject NodeId="ns=1;s={ied_node_id}"
            BrowseName="1:{browse_name}"
            ParentNodeId="ns=1;s=WindFarm">
    <DisplayName>{display_name}</DisplayName>
    <References>
      <Reference ReferenceType="HasTypeDefinition">BaseObjectType</Reference>
      <Reference ReferenceType="HasComponent" IsForward="false">ns=1;s=WindFarm</Reference>
    </References>
  </UAObject>
"""


# 变量节点模板。
#
# 每个 SimulatedPoint 最终生成一个 UAVariable。
#
# 层级关系：
# LN object
#   └── DO variable
#
# 变量 NodeId：
# ns=1;s={IED}.{LD}.{LN}.{DO}
#
# BrowseName 只使用 do_name，例如 DevSt。
_VARIABLE_TEMPLATE = """  <UAVariable NodeId="ns=1;s={node_id}"
              BrowseName="1:{browse_name}"
              ParentNodeId="ns=1;s={parent_node_id}"
              DataType="{data_type}"
              ValueRank="-1">
    <DisplayName>{display_name}</DisplayName>
    <References>
      <Reference ReferenceType="HasTypeDefinition">BaseDataVariableType</Reference>
      <Reference ReferenceType="HasComponent" IsForward="false">ns=1;s={parent_node_id}</Reference>
    </References>
    <Value>
      <{data_type}>{initial_value}</{data_type}>
    </Value>
  </UAVariable>
"""

_FOOTER = """</UANodeSet>
"""


def opcua_data_type(scada_type: str | None) -> str:
    """将内部点位数据类型转换为 OPC UA 标量数据类型名称。"""

    normalized = str(scada_type or "FLOAT64").strip().upper()
    return _SCADA_TO_OPCUA_TYPE.get(normalized, "Double")


def format_opcua_initial_value(point: SimulatedPoint) -> str:
    """将 SimulatedPoint.initial_value 格式化为 NodeSet XML 中的初始值。

    注意：
    这里写入的是 XML 初始值，只用于 import_xml 后变量有一个初始 Value。
    source_simulator.py 启动后还会再写一次 DataValue，
    用于补充 SourceTimestamp / ServerTimestamp。
    """

    data_type = opcua_data_type(point.data_type)
    initial = point.initial_value

    if data_type == "Boolean":
        return "1" if bool(initial) else "0"

    if data_type == "Int32":
        return str(int(float(initial or 0)))

    if data_type == "String":
        return escape(str(initial or ""))

    return str(float(initial or 0.0))


def logical_path(connection: SourceConnection, point: SimulatedPoint) -> str:
    """生成稳定的完整逻辑路径：IED.LD.LN.DO。

    这个路径用于：
    1. 变量节点 NodeId；
    2. client 端 get_node("ns=...;s=...")；
    3. simulator.writes(...) 中的 full logical path 写入 key。

    示例：
    IED001.LD0.WPPD1.DevSt
    """

    return f"{connection.ied_name}.{connection.ld_name}.{point.ln_name}.{point.do_name}"


def ld_path(connection: SourceConnection) -> str:
    """生成 LD 对象的 NodeId 字符串：IED.LD。"""

    return f"{connection.ied_name}.{connection.ld_name}"


def ln_path(connection: SourceConnection, point: SimulatedPoint) -> str:
    """生成 LN 对象的 NodeId 字符串：IED.LD.LN。"""

    return f"{connection.ied_name}.{connection.ld_name}.{point.ln_name}"


def build_nodeset_xml(
    *,
    points: tuple[SimulatedPoint, ...],
    connection: SourceConnection,
    namespace_uri: str,
) -> str:
    """生成一个完整的 OPC UA NodeSet XML。

    生成结构：

    Objects
      └── WindFarm
            └── {ied_name}
                  └── {ld_name}
                        └── {ln_name}
                              └── {do_name}

    其中：
    - WindFarm 是业务容器；
    - IED / LD / LN 是对象节点；
    - DO 是变量节点；
    - 变量 NodeId 不包含 WindFarm，只包含 IED.LD.LN.DO。
    """

    last_modified = datetime.now(tz=UTC).strftime("%Y-%m-%dT%H:%M:%SZ")

    parts: list[str] = [
        _HEADER.format(
            last_modified=last_modified,
            namespace_uri=escape(namespace_uri),
        )
    ]

    ied_node_id = connection.ied_name
    ld_node_id = ld_path(connection)

    # 1. 创建 IED 对象：
    #
    # Objects
    #   └── WindFarm
    #         └── IED001
    parts.append(
        _IED_OBJECT_TEMPLATE.format(
            ied_node_id=escape(ied_node_id),
            browse_name=escape(connection.ied_name),
            display_name=escape(connection.ied_name),
        )
    )

    # 2. 创建 LD 对象：
    #
    # Objects
    #   └── WindFarm
    #         └── IED001
    #               └── LD0
    parts.append(
        _OBJECT_TEMPLATE.format(
            node_id=escape(ld_node_id),
            browse_name=escape(connection.ld_name),
            parent_node_id=escape(ied_node_id),
            display_name=escape(connection.ld_name),
        )
    )

    # 记录已经创建过的 LN，避免多个 DO 属于同一个 LN 时重复创建 LN 对象。
    seen_lns: set[str] = set()

    # 记录已经创建过的变量点，避免重复生成同一个 DO 变量。
    seen_points: set[str] = set()

    for point in points:
        ln_node_id = ln_path(connection, point)

        # 3. 创建 LN 对象：
        #
        # Objects
        #   └── WindFarm
        #         └── IED001
        #               └── LD0
        #                     └── WPPD1
        if ln_node_id not in seen_lns:
            seen_lns.add(ln_node_id)

            parts.append(
                _OBJECT_TEMPLATE.format(
                    node_id=escape(ln_node_id),
                    browse_name=escape(point.ln_name),
                    parent_node_id=escape(ld_node_id),
                    display_name=escape(point.ln_name),
                )
            )

        variable_node_id = logical_path(connection, point)

        if variable_node_id in seen_points:
            continue

        seen_points.add(variable_node_id)

        display_name = point.display_name or point.do_name
        if point.unit:
            display_name = f"{display_name} ({point.unit})"

        # 4. 创建 DO 变量：
        #
        # Objects
        #   └── WindFarm
        #         └── IED001
        #               └── LD0
        #                     └── WPPD1
        #                           └── DevSt
        #
        # 变量 NodeId：
        # ns=1;s=IED001.LD0.WPPD1.DevSt
        parts.append(
            _VARIABLE_TEMPLATE.format(
                node_id=escape(variable_node_id),
                browse_name=escape(point.do_name),
                parent_node_id=escape(ln_node_id),
                data_type=opcua_data_type(point.data_type),
                display_name=escape(display_name),
                initial_value=format_opcua_initial_value(point),
            )
        )

    parts.append(_FOOTER)

    return "".join(parts)