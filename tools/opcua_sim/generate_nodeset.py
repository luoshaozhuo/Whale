"""Generate OPC UA NodeSet XML from GB/T 30966.2 field definitions.

Usage::

    from tools.opcua_sim.generate_nodeset import generate_nodeset_xml
    xml = generate_nodeset_xml(turbine_count=2)
    Path("nodeset.xml").write_text(xml)
"""

from __future__ import annotations

from datetime import UTC, datetime

from tools.opcua_sim.templates.gbt_30966_fields import ALL_LOGICAL_NODES, LogicalNodeField

_HEADER = """<?xml version="1.0" encoding="utf-8"?>
<UANodeSet xmlns="http://opcfoundation.org/UA/2011/03/UANodeSet.xsd"
           LastModified="{last_modified}">
  <NamespaceUris>
    <Uri>http://opcfoundation.org/UA/</Uri>
    <Uri>urn:windfarm:2wtg</Uri>
  </NamespaceUris>
  <Aliases>
    <Alias Alias="BaseObjectType">i=58</Alias>
    <Alias Alias="FolderType">i=61</Alias>
    <Alias Alias="BaseDataVariableType">i=63</Alias>
    <Alias Alias="ObjectsFolder">i=85</Alias>
    <Alias Alias="HasTypeDefinition">i=40</Alias>
    <Alias Alias="HasModellingRule">i=37</Alias>
    <Alias Alias="Organizes">i=35</Alias>
    <Alias Alias="HasComponent">i=47</Alias>
    <Alias Alias="Mandatory">i=78</Alias>
    <Alias Alias="Double">i=11</Alias>
  </Aliases>
  <UAObject NodeId="ns=1;s=WindFarm" BrowseName="1:WindFarm">
    <DisplayName>WindFarm</DisplayName>
    <References>
      <Reference ReferenceType="Organizes" IsForward="false">ObjectsFolder</Reference>
      <Reference ReferenceType="HasTypeDefinition">FolderType</Reference>
    </References>
  </UAObject>
"""

_TURBINE_TYPE_START = """  <UAObjectType NodeId="ns=1;s=WindTurbineType"
                BrowseName="1:WindTurbineType"
                IsAbstract="false">
    <DisplayName>WindTurbineType</DisplayName>
    <References>
      <Reference ReferenceType="HasSubtype" IsForward="false">BaseObjectType</Reference>
    </References>
  </UAObjectType>
"""

_VARIABLE_TEMPLATE = """  <UAVariable NodeId="ns=1;s=WindTurbineType.{key}"
              BrowseName="1:{key}"
              ParentNodeId="ns=1;s=WindTurbineType"
              DataType="{data_type}"
              ValueRank="-1">
    <DisplayName>{display_name}</DisplayName>
    <References>
      <Reference ReferenceType="HasModellingRule">Mandatory</Reference>
      <Reference ReferenceType="HasTypeDefinition">BaseDataVariableType</Reference>
      <Reference ReferenceType="HasComponent" IsForward="false">ns=1;s=WindTurbineType</Reference>
    </References>
    <Value>
      <{data_type}>{mean_val}</{data_type}>
    </Value>
  </UAVariable>
"""

_TURBINE_INSTANCE_TEMPLATE = """  <UAObject NodeId="ns=1;s={name}" BrowseName="1:{name}" ParentNodeId="ns=1;s=WindFarm">
    <DisplayName>{name}</DisplayName>
    <References>
      <Reference ReferenceType="Organizes" IsForward="false">ns=1;s=WindFarm</Reference>
      <Reference ReferenceType="HasTypeDefinition">ns=1;s=WindTurbineType</Reference>
    </References>
  </UAObject>
"""

_FOOTER = """</UANodeSet>
"""


def generate_nodeset_xml(
    turbine_count: int = 2,
    fields: list[LogicalNodeField] | None = None,
    turbine_name_prefix: str = "WTG_",
) -> str:
    """Generate OPC UA NodeSet XML with all variables as direct children of WindTurbineType.

    Args:
        turbine_count: Number of turbine instances to create.
        fields: Optional custom field list. If None, use all GB/T 30966 fields.
        turbine_name_prefix: Prefix for turbine instance BrowseNames.
    """
    if fields is None:
        all_fields: list[LogicalNodeField] = []
        for node in ALL_LOGICAL_NODES:
            all_fields.extend(node.fields)
        fields = all_fields

    last_modified = datetime.now(tz=UTC).strftime("%Y-%m-%dT%H:%M:%SZ")

    parts: list[str] = [_HEADER.format(last_modified=last_modified)]
    parts.append(_TURBINE_TYPE_START)

    for field in fields:
        data_type = getattr(field, "data_type", "Double") or "Double"
        if data_type == "Int32":
            mean_val = str(int(field.mean))
        elif data_type == "Boolean":
            mean_val = "1" if field.mean >= 0.5 else "0"
        elif data_type == "String":
            mean_val = str(field.desc)
        else:
            mean_val = str(field.mean)
        parts.append(
            _VARIABLE_TEMPLATE.format(
                key=field.key,
                display_name=f"{field.desc} ({field.unit})" if field.unit else field.desc,
                data_type=data_type,
                mean_val=mean_val,
            )
        )

    for i in range(1, turbine_count + 1):
        parts.append(_TURBINE_INSTANCE_TEMPLATE.format(name=f"{turbine_name_prefix}{i:02d}"))

    parts.append(_FOOTER)
    return "".join(parts)


def generate_small_nodeset_xml() -> str:
    """Generate a NodeSet with just the original 3 variables (for backward compat)."""
    small_fields = [
        LogicalNodeField("TotW", 1200.0, "kW", "Total Active Power"),
        LogicalNodeField("Spd", 12.5, "r/min", "Rotor Speed"),
        LogicalNodeField("WS", 6.8, "m/s", "Wind Speed"),
    ]
    return generate_nodeset_xml(turbine_count=2, fields=small_fields)
