"""Integration test for the DWD-to-DWS subchain."""

from __future__ import annotations

from pathlib import Path

import pytest

from whale.pipeline import Scenario1Pipeline


@pytest.mark.integration
def test_pipeline_dwd_to_dws(
    tmp_path: Path,
    sample_scl_path: Path,
    sample_raw_payloads: list[dict[str, object]],
    sample_power_curve_path: Path,
) -> None:
    """Verify realtime and periodic DWS aggregation from DWD."""
    pipeline = Scenario1Pipeline(tmp_path / "ods.sqlite", tmp_path / "dwd.sqlite")

    result = pipeline.run(sample_scl_path, sample_raw_payloads, sample_power_curve_path)

    assert len(result.realtime_results) > 0
    assert len(result.periodic_results) > 0
    assert result.periodic_results[0].energy_increment_kwh >= 0
    assert result.realtime_results[-1].avg_active_power_kw is not None
