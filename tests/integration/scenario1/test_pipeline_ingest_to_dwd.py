"""Integration test for the ingest-to-DWD subchain."""

from __future__ import annotations

from pathlib import Path

import pytest

from whale.scenario1.pipeline import Scenario1Pipeline
from whale.shared.enums.quality import QualityCode


@pytest.mark.integration
def test_pipeline_ingest_to_dwd(
    tmp_path: Path,
    sample_scl_path: Path,
    sample_raw_payloads: list[dict[str, object]],
    sample_power_curve_path: Path,
) -> None:
    """Verify SCL, ODS, normalize, clean, and DWD together."""
    pipeline = Scenario1Pipeline(tmp_path / "ods.sqlite", tmp_path / "dwd.sqlite")

    pipeline.run(sample_scl_path, sample_raw_payloads, sample_power_curve_path)
    records = pipeline.dwd_repository.list_records()

    assert pipeline.ods_repository.count_raw_batches() == len(sample_raw_payloads)
    assert pipeline.ods_repository.count_keyframes() == 2
    assert len(records) > 0
    assert any(record.point_code == "active_power_kw" for record in records)
    assert any(record.point_code == "wind_speed_ms" for record in records)
    assert any(
        record.point_code == "generator_bearing_temp_c"
        and record.quality_code == QualityCode.CORRECTED
        for record in records
    )
