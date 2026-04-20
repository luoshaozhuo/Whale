"""Unit tests for SCL registry parsing."""

from __future__ import annotations

from pathlib import Path

import pytest

from whale.scl_registry import SclRegistryError, parse_scl_registry


@pytest.mark.unit
def test_parse_minimal_scl_success(sample_scl_path: Path) -> None:
    """Parse the sample SCL into a usable registry."""
    registry = parse_scl_registry(sample_scl_path)

    assert len(registry) == 7
    assert registry[0].point_code == "active_power_kw"
    assert registry[0].opcua_node_id == "ns=2;s=power"


@pytest.mark.unit
def test_parse_scl_missing_required_field(tmp_path: Path) -> None:
    """Raise when a required SCL field is missing."""
    invalid_scl = tmp_path / "invalid.xml"
    invalid_scl.write_text(
        (
            '<scl><points><point turbine_id="T-1" point_code="active_power_kw" '
            'value_type="float" unit="kW" /></points></scl>'
        ),
        encoding="utf-8",
    )

    with pytest.raises(SclRegistryError, match="opcua_node_id"):
        parse_scl_registry(invalid_scl)


@pytest.mark.unit
def test_parse_scl_registry_fields_are_correct(sample_scl_path: Path) -> None:
    """Expose optional fields from the minimal SCL subset."""
    registry = parse_scl_registry(sample_scl_path)
    power = next(item for item in registry if item.point_code == "active_power_kw")

    assert power.min_value == 0.0
    assert power.max_value == 3000.0
    assert power.deadband == 0.2
    assert power.max_rate_of_change == 1200.0
