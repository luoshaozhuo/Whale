"""Unit tests for the DWD repository."""

from __future__ import annotations

from pathlib import Path

import pytest

from whale.models import PointMeta
from whale.processing.cleaner import PointCleaner
from whale.processing.normalizer import normalize_batch
from whale.raw_batch import build_raw_batch
from whale.ingest.adapter.repositories.repositories import DwdRepository


@pytest.mark.unit
def test_dwd_repository_saves_and_queries_records(
    tmp_path: Path,
    sample_raw_payloads: list[dict[str, object]],
    scenario1_registry: list[PointMeta],
    scenario1_registry_maps: tuple[dict[str, PointMeta], dict[str, PointMeta]],
) -> None:
    """Persist cleaned points and read them back."""
    repo = DwdRepository(tmp_path / "dwd.sqlite")
    batch = build_raw_batch(sample_raw_payloads[0])
    registry_by_node, registry_by_code = scenario1_registry_maps
    cleaner = PointCleaner()

    for point in normalize_batch(batch, registry_by_node, registry_by_code):
        meta = next(item for item in scenario1_registry if item.point_code == point.point_code)
        repo.write_clean_result(cleaner.clean(point, meta))

    records = repo.list_records()

    assert repo.count() == 7
    assert len(records) == 7
    assert any(record.point_code == "active_power_kw" for record in records)
