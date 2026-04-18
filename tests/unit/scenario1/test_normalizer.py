"""Unit tests for batch normalization."""

from __future__ import annotations

import pytest

from whale.scenario1.collector import build_raw_batch
from whale.scenario1.models import PointMeta
from whale.scenario1.normalizer import NormalizationError, normalize_batch
from whale.shared.enums.quality import RunState


@pytest.mark.unit
def test_raw_batch_normalizes_to_points(
    sample_raw_payloads: list[dict[str, object]],
    scenario1_registry_maps: tuple[dict[str, PointMeta], dict[str, PointMeta]],
) -> None:
    """Normalize a sample batch into stable points."""
    batch = build_raw_batch(sample_raw_payloads[0])
    registry_by_node, registry_by_code = scenario1_registry_maps

    points = normalize_batch(batch, registry_by_node, registry_by_code)

    assert len(points) == 7
    assert points[0].turbine_id == "T-100"
    assert any(point.point_code == "wind_speed_ms" for point in points)
    assert (
        next(point for point in points if point.point_code == "run_state").value
        == RunState.STARTING
    )


@pytest.mark.unit
def test_normalizer_mapping_is_correct(
    sample_raw_payloads: list[dict[str, object]],
    scenario1_registry_maps: tuple[dict[str, PointMeta], dict[str, PointMeta]],
) -> None:
    """Use node ids to resolve point metadata."""
    batch = build_raw_batch(sample_raw_payloads[1])
    registry_by_node, registry_by_code = scenario1_registry_maps

    points = normalize_batch(batch, registry_by_node, registry_by_code)
    power = next(point for point in points if point.point_code == "active_power_kw")

    assert power.source_node_id == "ns=2;s=power"
    assert power.value == 1010.0
    assert power.unit == "kW"


@pytest.mark.unit
def test_normalizer_missing_mapping_raises(
    sample_raw_payloads: list[dict[str, object]],
    scenario1_registry_maps: tuple[dict[str, PointMeta], dict[str, PointMeta]],
) -> None:
    """Raise on unknown measurements instead of swallowing them."""
    payload = dict(sample_raw_payloads[0])
    payload["measurements"] = [{"node_id": "ns=2;s=unknown", "value": 1.0, "status": "GOOD"}]
    batch = build_raw_batch(payload)
    registry_by_node, registry_by_code = scenario1_registry_maps

    with pytest.raises(NormalizationError, match="mapping missing"):
        normalize_batch(batch, registry_by_node, registry_by_code)
