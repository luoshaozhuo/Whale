"""SCL registry parsing for scenario1 minimal subset."""

from __future__ import annotations

from pathlib import Path
from xml.etree import ElementTree

from whale.scenario1.models import SUPPORTED_POINT_CODES, PointMeta

REQUIRED_SCL_FIELDS = {
    "turbine_id",
    "point_code",
    "opcua_node_id",
    "value_type",
    "unit",
}

OPTIONAL_FLOAT_FIELDS = {"min_value", "max_value", "deadband", "max_rate_of_change"}


class SclRegistryError(ValueError):
    """Raised when the minimal SCL subset is invalid."""


def parse_scl_registry(path: str | Path) -> list[PointMeta]:
    """Parse a minimal SCL XML file into point metadata.

    Args:
        path: SCL XML path.

    Returns:
        Parsed point metadata list.

    Raises:
        SclRegistryError: If required fields are missing or XML is invalid.
    """
    xml_path = Path(path)
    root = ElementTree.parse(xml_path).getroot()
    points = root.findall(".//point")
    if not points:
        raise SclRegistryError("No <point> entries found in SCL file.")

    registry: list[PointMeta] = []
    for index, point in enumerate(points, start=1):
        attrs = {key: value for key, value in point.attrib.items()}
        missing_fields = sorted(field for field in REQUIRED_SCL_FIELDS if not attrs.get(field))
        if missing_fields:
            missing = ", ".join(missing_fields)
            raise SclRegistryError(f"Point #{index} missing required fields: {missing}")

        point_code = attrs["point_code"]
        if point_code not in SUPPORTED_POINT_CODES:
            raise SclRegistryError(f"Unsupported point_code in scenario1: {point_code}")

        registry.append(
            PointMeta(
                turbine_id=attrs["turbine_id"],
                point_code=point_code,
                opcua_node_id=attrs["opcua_node_id"],
                value_type=attrs["value_type"],
                unit=attrs["unit"],
                min_value=_parse_optional_float(attrs.get("min_value")),
                max_value=_parse_optional_float(attrs.get("max_value")),
                deadband=_parse_optional_float(attrs.get("deadband")),
                max_rate_of_change=_parse_optional_float(attrs.get("max_rate_of_change")),
                aggregate_group=attrs.get("aggregate_group"),
            )
        )
    return registry


def build_registry_maps(
    registry: list[PointMeta],
) -> tuple[dict[str, PointMeta], dict[str, PointMeta]]:
    """Build registry lookup maps for normalization and cleaning.

    Args:
        registry: Parsed point metadata list.

    Returns:
        A pair of lookup tables keyed by OPC UA node id and internal point code.
    """
    by_node = {item.opcua_node_id: item for item in registry}
    by_code = {item.point_code: item for item in registry}
    return by_node, by_code


def _parse_optional_float(value: str | None) -> float | None:
    """Parse an optional numeric field."""
    if value is None or value == "":
        return None
    return float(value)
