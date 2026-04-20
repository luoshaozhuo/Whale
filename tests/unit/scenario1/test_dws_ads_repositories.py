"""Unit tests for DWS and ADS repositories."""

from __future__ import annotations

import pytest

from whale.models import (
    AdsAvailability,
    AdsPowerCurveDeviation,
    DwsPeriodicAggregate,
    DwsRealtimeAggregate,
)
from whale.shared.enums.quality import RunState
from whale.shared.utils.time import parse_iso_datetime
from whale.ingest.adapter.repositories.repositories import AdsRepository, DwsRepository


@pytest.mark.unit
def test_dws_and_ads_repositories_save_and_query() -> None:
    """Save and query DWS and ADS aggregate results."""
    dws_repo = DwsRepository()
    ads_repo = AdsRepository()
    timestamp = parse_iso_datetime("2026-04-18T12:00:00Z")

    dws_repo.write_realtime(
        [
            DwsRealtimeAggregate(
                window_end_time=timestamp,
                turbine_id="T-100",
                avg_active_power_kw=1200.0,
                avg_wind_speed_ms=6.5,
                max_generator_bearing_temp_c=50.0,
                run_state_last=RunState.RUNNING,
                bad_quality_ratio=0.0,
            )
        ]
    )
    dws_repo.write_periodic(
        [
            DwsPeriodicAggregate(
                bucket_time=timestamp.replace(second=0, microsecond=0),
                turbine_id="T-100",
                energy_increment_kwh=2.0,
                avg_active_power_kw=1200.0,
                avg_pitch_angle_deg=2.5,
            )
        ]
    )
    ads_repo.write_power_curve(
        [
            AdsPowerCurveDeviation(
                bucket_time=timestamp.replace(second=0, microsecond=0),
                turbine_id="T-100",
                wind_speed_bin=6.5,
                actual_power_kw=1200.0,
                theoretical_power_kw=1100.0,
                deviation_kw=100.0,
            )
        ]
    )
    ads_repo.write_availability(
        [
            AdsAvailability(
                bucket_time=timestamp.replace(second=0, microsecond=0),
                turbine_id="T-100",
                availability_ratio=0.5,
                run_time_sec=30.0,
                bad_quality_ratio=0.1,
            )
        ]
    )

    assert len(dws_repo.list_realtime()) == 1
    assert len(dws_repo.list_periodic()) == 1
    assert len(ads_repo.list_power_curve()) == 1
    assert len(ads_repo.list_availability()) == 1
