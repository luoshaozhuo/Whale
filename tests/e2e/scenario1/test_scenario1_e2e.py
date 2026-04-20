"""Scenario1 e2e coverage.

Scenario-Name: scenario1
Scenario-Goal: 风机实时数据接入与分层存储最小闭环
Main-Flow:
1. load SCL registry [implemented]
2. ingest raw OPC UA batches [implemented]
3. persist ODS raw batches/keyframes [implemented]
4. normalize raw points [implemented]
5. clean normalized points [implemented]
6. persist DWD records [implemented]
7. aggregate DWS realtime/periodic [implemented]
8. aggregate ADS business results [implemented]
Verification:
- full scenario1 pipeline is stable
"""

from __future__ import annotations

from pathlib import Path

import pytest

from whale.pipeline import Scenario1Pipeline


@pytest.mark.e2e
def test_scenario1_e2e(
    tmp_path: Path,
    sample_scl_path: Path,
    sample_raw_payloads: list[dict[str, object]],
    sample_power_curve_path: Path,
) -> None:
    """Run the full scenario1 main flow end to end."""
    pipeline = Scenario1Pipeline(tmp_path / "ods.sqlite", tmp_path / "dwd.sqlite")

    result = pipeline.run(sample_scl_path, sample_raw_payloads, sample_power_curve_path)

    assert pipeline.ods_repository.count_raw_batches() > 0
    assert pipeline.ods_repository.count_keyframes() > 0
    assert pipeline.dwd_repository.count() > 0
    assert len(result.realtime_results) > 0
    assert len(result.periodic_results) > 0
    assert len(result.power_curve_results) > 0
    assert len(result.availability_results) > 0
    assert all(item.energy_increment_kwh >= 0 for item in result.periodic_results)
    assert all(0.0 <= item.availability_ratio <= 1.0 for item in result.availability_results)
