"""Unit tests for periodic aggregation."""

from __future__ import annotations

import pytest

from whale.scenario1.models import DwdRecord
from whale.scenario1.periodic_aggregator import aggregate_periodic
from whale.shared.enums.quality import QualityCode
from whale.shared.utils.time import parse_iso_datetime


@pytest.mark.unit
def test_periodic_aggregator_computes_minute_bucket() -> None:
    """Aggregate 1-minute bucket metrics."""
    records = [
        DwdRecord(
            parse_iso_datetime("2026-04-18T12:00:00Z"),
            parse_iso_datetime("2026-04-18T12:00:00Z"),
            "T-100",
            "active_power_kw",
            1200.0,
            QualityCode.GOOD,
        ),
        DwdRecord(
            parse_iso_datetime("2026-04-18T12:00:10Z"),
            parse_iso_datetime("2026-04-18T12:00:10Z"),
            "T-100",
            "active_power_kw",
            1800.0,
            QualityCode.GOOD,
        ),
        DwdRecord(
            parse_iso_datetime("2026-04-18T12:00:20Z"),
            parse_iso_datetime("2026-04-18T12:00:20Z"),
            "T-100",
            "active_power_kw",
            2400.0,
            QualityCode.GOOD,
        ),
        DwdRecord(
            parse_iso_datetime("2026-04-18T12:00:00Z"),
            parse_iso_datetime("2026-04-18T12:00:00Z"),
            "T-100",
            "pitch_angle_deg",
            2.0,
            QualityCode.GOOD,
        ),
        DwdRecord(
            parse_iso_datetime("2026-04-18T12:00:20Z"),
            parse_iso_datetime("2026-04-18T12:00:20Z"),
            "T-100",
            "pitch_angle_deg",
            4.0,
            QualityCode.GOOD,
        ),
    ]

    results = aggregate_periodic(records)
    result = results[0]

    assert result.bucket_time == parse_iso_datetime("2026-04-18T12:00:00Z").replace(
        second=0, microsecond=0
    )
    assert result.energy_increment_kwh >= 0
    assert result.avg_active_power_kw == pytest.approx((1200.0 + 1800.0 + 2400.0) / 3)
    assert result.avg_pitch_angle_deg == pytest.approx(3.0)
