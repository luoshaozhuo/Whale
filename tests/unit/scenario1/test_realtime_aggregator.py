"""Unit tests for realtime aggregation."""

from __future__ import annotations

import pytest

from whale.aggregation.realtime import aggregate_realtime
from whale.models import DwdRecord
from whale.shared.enums.quality import QualityCode, RunState
from whale.shared.utils.time import parse_iso_datetime


@pytest.mark.unit
def test_realtime_aggregator_computes_window_metrics() -> None:
    """Compute sliding-window metrics from DWD records."""
    records = [
        DwdRecord(
            parse_iso_datetime("2026-04-18T12:00:00Z"),
            parse_iso_datetime("2026-04-18T12:00:00Z"),
            "T-100",
            "active_power_kw",
            1000.0,
            QualityCode.GOOD,
        ),
        DwdRecord(
            parse_iso_datetime("2026-04-18T12:00:01Z"),
            parse_iso_datetime("2026-04-18T12:00:01Z"),
            "T-100",
            "active_power_kw",
            1100.0,
            QualityCode.GOOD,
        ),
        DwdRecord(
            parse_iso_datetime("2026-04-18T12:00:02Z"),
            parse_iso_datetime("2026-04-18T12:00:02Z"),
            "T-100",
            "wind_speed_ms",
            6.0,
            QualityCode.GOOD,
        ),
        DwdRecord(
            parse_iso_datetime("2026-04-18T12:00:03Z"),
            parse_iso_datetime("2026-04-18T12:00:03Z"),
            "T-100",
            "wind_speed_ms",
            8.0,
            QualityCode.BAD,
        ),
        DwdRecord(
            parse_iso_datetime("2026-04-18T12:00:04Z"),
            parse_iso_datetime("2026-04-18T12:00:04Z"),
            "T-100",
            "generator_bearing_temp_c",
            50.0,
            QualityCode.GOOD,
        ),
        DwdRecord(
            parse_iso_datetime("2026-04-18T12:00:04Z"),
            parse_iso_datetime("2026-04-18T12:00:04Z"),
            "T-100",
            "run_state",
            RunState.RUNNING,
            QualityCode.GOOD,
        ),
        DwdRecord(
            parse_iso_datetime("2026-04-18T12:00:05Z"),
            parse_iso_datetime("2026-04-18T12:00:05Z"),
            "T-100",
            "active_power_kw",
            1200.0,
            QualityCode.SUSPECT,
        ),
    ]

    results = aggregate_realtime(records)
    last = results[-1]

    assert results[0].window_end_time == parse_iso_datetime("2026-04-18T12:00:00Z")
    assert last.window_end_time == parse_iso_datetime("2026-04-18T12:00:05Z")
    assert last.avg_active_power_kw == pytest.approx((1000.0 + 1100.0 + 1200.0) / 3)
    assert last.avg_wind_speed_ms == pytest.approx(6.0)
    assert last.max_generator_bearing_temp_c == 50.0
    assert last.run_state_last == RunState.RUNNING
    assert last.bad_quality_ratio == pytest.approx(2 / 7)
