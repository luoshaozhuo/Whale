"""Unit tests for fleet point-selection logic under UpdateConfig."""

from __future__ import annotations

import pytest

from tools.source_simulation.domain import SharedPoint, UpdateConfig
from tools.source_simulation.fleet import SourceSimulatorFleet


def _point(path: str) -> SharedPoint:
    return SharedPoint(
        path=path,
        data_type="FLOAT64",
        initial_value=1.0,
    )


@pytest.mark.unit
def test_select_points_uses_update_count_before_update_ratio() -> None:
    """Apply update_count first when both update_count and update_ratio are set."""
    fleet = SourceSimulatorFleet(
        simulators=[],
        update_config=UpdateConfig(interval_seconds=1.0, update_count=2, update_ratio=0.25),
        _shared_points=(_point("P1"), _point("P2"), _point("P3"), _point("P4")),
    )

    selected = fleet._select_points_for_update()

    assert [point.path for point in selected] == ["P1", "P2"]


@pytest.mark.unit
def test_select_points_uses_ratio_when_count_is_absent() -> None:
    """Apply update_ratio when update_count is not configured."""
    fleet = SourceSimulatorFleet(
        simulators=[],
        update_config=UpdateConfig(interval_seconds=1.0, update_ratio=0.25),
        _shared_points=(_point("P1"), _point("P2"), _point("P3"), _point("P4")),
    )

    selected = fleet._select_points_for_update()

    assert [point.path for point in selected] == ["P1"]
