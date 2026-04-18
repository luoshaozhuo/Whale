"""Integration test for the DWD/DWS-to-ADS subchain."""

from __future__ import annotations

from pathlib import Path

import pytest

from whale.scenario1.pipeline import Scenario1Pipeline


@pytest.mark.integration
def test_pipeline_dws_to_ads(
    tmp_path: Path,
    sample_scl_path: Path,
    sample_raw_payloads: list[dict[str, object]],
    sample_power_curve_path: Path,
) -> None:
    """Verify ADS business aggregations from DWD and DWS outputs."""
    pipeline = Scenario1Pipeline(tmp_path / "ods.sqlite", tmp_path / "dwd.sqlite")

    result = pipeline.run(sample_scl_path, sample_raw_payloads, sample_power_curve_path)

    assert len(result.power_curve_results) > 0
    assert len(result.availability_results) > 0
    assert 0.0 <= result.availability_results[0].availability_ratio <= 1.0
