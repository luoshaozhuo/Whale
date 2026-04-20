"""Smoke test for the scenario1 pipeline."""

from __future__ import annotations

from pathlib import Path

import pytest

from whale.pipeline import Scenario1Pipeline


@pytest.mark.smoke
def test_pipeline_smoke_runs_minimal_flow(
    tmp_path: Path,
    sample_scl_path: Path,
    sample_raw_payloads: list[dict[str, object]],
    sample_power_curve_path: Path,
) -> None:
    """Run the minimal pipeline without crashing."""
    pipeline = Scenario1Pipeline(tmp_path / "ods.sqlite", tmp_path / "dwd.sqlite")

    result = pipeline.run(sample_scl_path, sample_raw_payloads, sample_power_curve_path)

    assert result.raw_batches_written > 0
    assert pipeline.ods_repository.count_raw_batches() > 0
    assert pipeline.ods_repository.count_keyframes() > 0
    assert pipeline.dwd_repository.count() > 0
