"""Unit tests for ADS aggregators."""

from __future__ import annotations

import pytest

from whale.aggregation.ads import aggregate_availability, aggregate_power_curve_deviation
from whale.models import DwdRecord, DwsPeriodicAggregate
from whale.shared.enums.quality import QualityCode, RunState
from whale.shared.utils.time import parse_iso_datetime


@pytest.mark.unit
def test_ads_power_curve_and_availability() -> None:
    """Compute power-curve deviation and bounded availability."""
    bucket_time = parse_iso_datetime("2026-04-18T12:00:00Z").replace(second=0, microsecond=0)
    dwd_records = [
        DwdRecord(
            parse_iso_datetime("2026-04-18T12:00:00Z"),
            parse_iso_datetime("2026-04-18T12:00:00Z"),
            "T-100",
            "wind_speed_ms",
            7.1,
            QualityCode.GOOD,
        ),
        DwdRecord(
            parse_iso_datetime("2026-04-18T12:00:10Z"),
            parse_iso_datetime("2026-04-18T12:00:10Z"),
            "T-100",
            "wind_speed_ms",
            6.9,
            QualityCode.GOOD,
        ),
        DwdRecord(
            parse_iso_datetime("2026-04-18T12:00:00Z"),
            parse_iso_datetime("2026-04-18T12:00:00Z"),
            "T-100",
            "run_state",
            RunState.RUNNING,
            QualityCode.GOOD,
        ),
        DwdRecord(
            parse_iso_datetime("2026-04-18T12:00:30Z"),
            parse_iso_datetime("2026-04-18T12:00:30Z"),
            "T-100",
            "run_state",
            RunState.STOPPED,
            QualityCode.GOOD,
        ),
    ]
    periodic_results = [
        DwsPeriodicAggregate(
            bucket_time=bucket_time,
            turbine_id="T-100",
            energy_increment_kwh=5.0,
            avg_active_power_kw=1500.0,
            avg_pitch_angle_deg=2.5,
        )
    ]
    power_curve = {7.0: 1400.0}

    deviation_results = aggregate_power_curve_deviation(dwd_records, periodic_results, power_curve)
    availability_results = aggregate_availability(dwd_records)

    assert deviation_results[0].wind_speed_bin == 7.0
    assert deviation_results[0].theoretical_power_kw == 1400.0
    assert deviation_results[0].deviation_kw == pytest.approx(100.0)
    assert 0.0 <= availability_results[0].availability_ratio <= 1.0
