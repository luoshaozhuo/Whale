"""Unit tests for ODS raw batch and keyframe behavior."""

from __future__ import annotations

from pathlib import Path

import pytest

from whale.pipeline import Scenario1Pipeline


@pytest.mark.unit
def test_pipeline_writes_ods_raw_batches_and_keyframes(
    tmp_path: Path,
    sample_scl_path: Path,
    sample_raw_payloads: list[dict[str, object]],
    sample_power_curve_path: Path,
) -> None:
    """Write raw batches and a deduplicated keyframe stream."""
    pipeline = Scenario1Pipeline(
        ods_db_path=tmp_path / "ods.sqlite",
        dwd_db_path=tmp_path / "dwd.sqlite",
        keyframe_interval_seconds=10,
    )

    result = pipeline.run(sample_scl_path, sample_raw_payloads, sample_power_curve_path)

    assert result.raw_batches_written == len(sample_raw_payloads)
    assert pipeline.ods_repository.count_raw_batches() == len(sample_raw_payloads)
    assert pipeline.ods_repository.count_keyframes() == 2
