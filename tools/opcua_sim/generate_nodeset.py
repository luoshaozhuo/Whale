"""Generate OPC UA NodeSet XML from GB/T 30966.2 field definitions.

Supports both the legacy static-field path and database-driven generation.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Iterable

# ── OPC UA type mapping (scada_data_type → OPC UA DataType) ────────────
_SCADA_TO_OPCUA_TYPE: dict[str, str] = {
    "FLOAT64": "Double",
    "FLOAT32": "Double",
    "INT8": "Int32",
    "INT16": "Int32",
    "INT32": "Int32",
    "INT64": "Int32",
    "INT8U": "Int32",
    "INT16U": "Int32",
    "INT32U": "Int32",
    "BOOLEAN": "Boolean",
    "VisString255": "String",
    "CODED_ENUM": "Int32",
    "TIMESTAMP": "String",
    "OCTET_STRING": "String",
}

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


def _opcua_type(scada_type: str | None) -> str:
    return _SCADA_TO_OPCUA_TYPE.get(str(scada_type or "FLOAT64"), "Double")


def _default_mean(scada_type: str | None) -> float:
    """Return a sensible default mean for simulation when none is provided."""
    t = str(scada_type or "FLOAT64")
    if t in ("BOOLEAN",):
        return 0.0
    if t == "INT32":
        return 0.0
    return 0.0


def _field_mean_from_dict(do_name: str, field_means: dict[str, float], data_type: str | None) -> float:
    """Look up the field mean from the gbt_30966 dict, falling back to defaults."""
    if do_name in field_means:
        return field_means[do_name]
    return _default_mean(data_type)


def _format_mean_val(mean: float, data_type: str) -> str:
    opc_type = _opcua_type(data_type)
    if opc_type == "Int32":
        return str(int(mean))
    if opc_type == "Boolean":
        return "1" if mean >= 0.5 else "0"
    if opc_type == "String":
        return str(mean)
    return str(mean)


def generate_nodeset_from_measurement_points(
    measurement_points: Iterable[dict],
    turbine_names: list[str],
    field_means: dict[str, float] | None = None,
) -> tuple[str, dict[str, float]]:
    """Generate OPC UA NodeSet XML from v_opcua_measurement_point query results.

    Args:
        measurement_points: Iterable of dicts with keys: do_name, data_type, unit, display_name.
        turbine_names: List of turbine BrowseNames (e.g. ["ZB-WTG-001", ...]).
        field_means: Optional pre-built {do_name: mean_value} dict. If None,
            means default to 0.0.

    Returns:
        (nodeset_xml_string, variable_means_dict)
    """
    if field_means is None:
        field_means = {}

    last_modified = datetime.now(tz=UTC).strftime("%Y-%m-%dT%H:%M:%SZ")

    parts: list[str] = [_HEADER.format(last_modified=last_modified)]
    parts.append(_TURBINE_TYPE_START)

    seen_keys: set[str] = set()
    variable_means: dict[str, float] = {}
    for mp in measurement_points:
        key = mp["do_name"]
        if key in seen_keys:
            continue
        seen_keys.add(key)

        data_type = mp.get("data_type", "FLOAT64")
        opc_type = _opcua_type(data_type)
        mean_val = _field_mean_from_dict(key, field_means, data_type)
        variable_means[key] = mean_val

        unit = mp.get("unit") or ""
        display_name = mp.get("display_name") or key
        if unit:
            display_name = f"{display_name} ({unit})"

        parts.append(
            _VARIABLE_TEMPLATE.format(
                key=key,
                display_name=display_name,
                data_type=opc_type,
                mean_val=_format_mean_val(mean_val, data_type),
            )
        )

    for name in turbine_names:
        parts.append(_TURBINE_INSTANCE_TEMPLATE.format(name=name))

    parts.append(_FOOTER)
    return "".join(parts), variable_means


def generate_small_nodeset_xml() -> str:
    """Minimal NodeSet with 3 variables for backward compat testing."""
    from dataclasses import dataclass

    @dataclass
    class _Field:
        key: str
        mean: float
        unit: str
        desc: str
        data_type: str = "Double"

    small_fields = [
        _Field("TotW", 1200.0, "kW", "Total Active Power"),
        _Field("Spd", 12.5, "r/min", "Rotor Speed"),
        _Field("WS", 6.8, "m/s", "Wind Speed"),
    ]
    xml, _ = generate_nodeset_from_measurement_points(
        measurement_points=[
            {"do_name": f.key, "data_type": f.data_type, "unit": f.unit, "display_name": f.desc}
            for f in small_fields
        ],
        turbine_names=["WTG_01", "WTG_02"],
        field_means={f.key: f.mean for f in small_fields},
    )
    return xml
