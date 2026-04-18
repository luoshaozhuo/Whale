"""Shared pytest fixtures."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import cast

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from whale.scenario1.models import PointMeta  # noqa: E402
from whale.scenario1.scl_registry import build_registry_maps, parse_scl_registry  # noqa: E402


@pytest.fixture()
def scenario1_fixture_dir() -> Path:
    """Return the directory that stores shared scenario1 fixtures.

    Returns:
        Fixture directory used by scenario1 tests.
    """
    return Path(__file__).parent / "fixtures" / "scenario1"


@pytest.fixture()
def sample_scl_path(scenario1_fixture_dir: Path) -> Path:
    """Return the sample SCL registry path for scenario1 tests.

    Args:
        scenario1_fixture_dir: Base fixture directory for scenario1.

    Returns:
        Path to the sample SCL file.
    """
    return scenario1_fixture_dir / "sample_scl.xml"


@pytest.fixture()
def sample_power_curve_path(scenario1_fixture_dir: Path) -> Path:
    """Return the sample power-curve CSV path for scenario1 tests.

    Args:
        scenario1_fixture_dir: Base fixture directory for scenario1.

    Returns:
        Path to the sample power-curve CSV file.
    """
    return scenario1_fixture_dir / "sample_power_curve.csv"


@pytest.fixture()
def sample_raw_payloads(scenario1_fixture_dir: Path) -> list[dict[str, object]]:
    """Load sample raw OPC UA payloads for scenario1 tests.

    Args:
        scenario1_fixture_dir: Base fixture directory for scenario1.

    Returns:
        Parsed mock raw batches loaded from the fixture JSON file.
    """
    return cast(
        list[dict[str, object]],
        json.loads((scenario1_fixture_dir / "sample_raw_batches.json").read_text(encoding="utf-8")),
    )


@pytest.fixture()
def scenario1_registry(sample_scl_path: Path) -> list[PointMeta]:
    """Load and parse the sample scenario1 registry.

    Args:
        sample_scl_path: Fixture path for the minimal SCL file.

    Returns:
        Parsed point metadata used by scenario1 tests.
    """
    return parse_scl_registry(sample_scl_path)


@pytest.fixture()
def scenario1_registry_maps(
    scenario1_registry: list[PointMeta],
) -> tuple[dict[str, PointMeta], dict[str, PointMeta]]:
    """Build scenario1 registry lookup maps for tests.

    Args:
        scenario1_registry: Parsed point metadata fixture.

    Returns:
        Lookup tables keyed by OPC UA node id and internal point code.
    """
    return build_registry_maps(scenario1_registry)
