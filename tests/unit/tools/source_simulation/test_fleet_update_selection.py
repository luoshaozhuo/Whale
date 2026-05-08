"""Unit tests for fleet update-point selection and write generation."""

from __future__ import annotations

import random

import pytest

from tools.source_simulation.domain import (
    SimulatedPoint,
    SimulatedSource,
    SourceConnection,
    UpdateConfig,
)
from tools.source_simulation.fleet import (
    SourceSimulatorFleet,
    _build_update_writes,
    _normalize_point_data_type,
    _select_points_for_update,
)


def _point(name: str, data_type: str = "FLOAT64") -> SimulatedPoint:
    return SimulatedPoint(
        ln_name="MMXU1",
        do_name=name,
        unit=None,
        data_type=data_type,
        initial_value=1.0,
    )


def _source(*points: SimulatedPoint) -> SimulatedSource:
    return SimulatedSource(
        connection=SourceConnection(
            name="WTG_01",
            ied_name="WTG_01",
            ld_name="LD0",
            host="127.0.0.1",
            port=4840,
            transport="tcp",
            protocol="opcua",
            namespace_uri="urn:test:fleet",
        ),
        points=tuple(points),
    )


@pytest.mark.unit
def test_create_keeps_external_fleet_api() -> None:
    fleet = SourceSimulatorFleet.create(
        sources=[_source(_point("P1"))],
        update_config=UpdateConfig(enabled=False, interval_seconds=1.0),
    )

    assert fleet.sources[0].connection.name == "WTG_01"
    assert fleet.update_config.enabled is False


@pytest.mark.unit
def test_create_rejects_empty_sources() -> None:
    with pytest.raises(ValueError, match="at least one source"):
        SourceSimulatorFleet.create([])


@pytest.mark.unit
def test_select_points_uses_update_count_before_update_ratio() -> None:
    selected = _select_points_for_update(
        [_point("P1"), _point("P2"), _point("P3"), _point("P4")],
        UpdateConfig(interval_seconds=1.0, update_count=2, update_ratio=0.25),
    )

    assert [point.key for point in selected] == ["MMXU1.P1", "MMXU1.P2"]


@pytest.mark.unit
def test_select_points_uses_ratio_when_count_is_absent() -> None:
    selected = _select_points_for_update(
        [_point("P1"), _point("P2"), _point("P3"), _point("P4")],
        UpdateConfig(interval_seconds=1.0, update_ratio=0.25),
    )

    assert [point.key for point in selected] == ["MMXU1.P1"]


@pytest.mark.unit
def test_select_points_returns_empty_when_no_points_exist() -> None:
    selected = _select_points_for_update([], UpdateConfig(interval_seconds=1.0))

    assert selected == ()


@pytest.mark.unit
def test_normalize_point_data_type_matches_legacy_semantics() -> None:
    assert _normalize_point_data_type("BOOL") == "BOOLEAN"
    assert _normalize_point_data_type("UINT16") == "INT32"
    assert _normalize_point_data_type("DOUBLE") == "FLOAT64"
    assert _normalize_point_data_type("TIMESTAMP") == "DATETIME"
    assert _normalize_point_data_type("TEXT") == "STRING"
    assert _normalize_point_data_type("UNKNOWN") == "FLOAT64"


@pytest.mark.unit
def test_build_update_writes_uses_point_key_instead_of_full_path() -> None:
    writes = _build_update_writes(
        [_point("TotW", "FLOAT64"), _point("TurSt", "BOOLEAN")],
        random.Random(20260508),
    )

    assert set(writes) == {"MMXU1.TotW", "MMXU1.TurSt"}
    assert isinstance(writes["MMXU1.TotW"], float)
    assert isinstance(writes["MMXU1.TurSt"], bool)
