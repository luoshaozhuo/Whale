"""Unit tests for scenario1 cleaning rules."""

from __future__ import annotations

import pytest

from whale.models import NormalizedPoint, PointMeta, ScalarValue
from whale.processing.cleaner import PointCleaner
from whale.shared.enums.quality import CleanAction, QualityCode
from whale.shared.utils.time import parse_iso_datetime


def _point(value: ScalarValue, *, event_time: str = "2026-04-18T12:00:00Z") -> NormalizedPoint:
    return NormalizedPoint(
        event_time=parse_iso_datetime(event_time),
        ingest_time=parse_iso_datetime("2026-04-18T12:00:00Z"),
        turbine_id="T-100",
        point_code="active_power_kw",
        value=value,
        value_type="float",
        unit="kW",
        source_status="GOOD",
        source_node_id="ns=2;s=power",
    )


def _meta(
    *,
    min_value: float | None = 0.0,
    max_value: float | None = 3000.0,
    deadband: float | None = 0.2,
    max_rate_of_change: float | None = 100.0,
) -> PointMeta:
    return PointMeta(
        turbine_id="T-100",
        point_code="active_power_kw",
        opcua_node_id="ns=2;s=power",
        value_type="float",
        unit="kW",
        min_value=min_value,
        max_value=max_value,
        deadband=deadband,
        max_rate_of_change=max_rate_of_change,
        aggregate_group="power",
    )


@pytest.mark.unit
def test_cleaner_validates_null_value() -> None:
    """Drop null values with a BAD quality code."""
    result = PointCleaner().clean(_point(None), _meta())

    assert result.quality_code == QualityCode.BAD
    assert result.clean_action == CleanAction.DROP
    assert "null" in result.clean_reason


@pytest.mark.unit
def test_cleaner_applies_range_clamp() -> None:
    """Clamp out-of-range values and record the reason."""
    result = PointCleaner().clean(_point(9999.0), _meta())

    assert result.quality_code == QualityCode.CORRECTED
    assert result.clean_action == CleanAction.CLAMP
    assert result.normalized_point.value == 3000.0
    assert "max_value" in result.clean_reason


@pytest.mark.unit
def test_cleaner_applies_deadband_hold_last() -> None:
    """Hold last value when the change is below deadband."""
    cleaner = PointCleaner()
    cleaner.clean(_point(1000.0), _meta())

    result = cleaner.clean(_point(1000.1, event_time="2026-04-18T12:00:01Z"), _meta())

    assert result.quality_code == QualityCode.CORRECTED
    assert result.clean_action == CleanAction.HOLD_LAST
    assert result.normalized_point.value == 1000.0


@pytest.mark.unit
def test_cleaner_applies_rate_rule() -> None:
    """Mark large rate jumps as suspect."""
    cleaner = PointCleaner()
    cleaner.clean(_point(1000.0), _meta(max_rate_of_change=10.0))

    result = cleaner.clean(
        _point(1300.0, event_time="2026-04-18T12:00:01Z"), _meta(max_rate_of_change=10.0)
    )

    assert result.quality_code == QualityCode.SUSPECT
    assert result.clean_action == CleanAction.KEEP
    assert "exceeds" in result.clean_reason


@pytest.mark.unit
def test_cleaner_validates_run_state_type() -> None:
    """Reject run_state values with the wrong type."""
    point = NormalizedPoint(
        event_time=parse_iso_datetime("2026-04-18T12:00:00Z"),
        ingest_time=parse_iso_datetime("2026-04-18T12:00:00Z"),
        turbine_id="T-100",
        point_code="run_state",
        value="RUNNING",
        value_type="enum",
        unit="state",
        source_status="GOOD",
        source_node_id="ns=2;s=state",
    )
    meta = PointMeta(
        turbine_id="T-100",
        point_code="run_state",
        opcua_node_id="ns=2;s=state",
        value_type="enum",
        unit="state",
    )

    result = PointCleaner().clean(point, meta)

    assert result.quality_code == QualityCode.BAD
    assert result.clean_action == CleanAction.DROP
