"""Unit tests for the file-backed variable-state repository."""

from __future__ import annotations

import csv
from datetime import UTC, datetime
from pathlib import Path

import pytest

from whale.ingest.adapters.state.file_source_state_cache import (
    FileSourceStateCache,
)
from whale.ingest.usecases.dtos.acquired_node_state import AcquiredNodeState


def _build_states() -> list[AcquiredNodeState]:
    """Build deterministic acquired states for repository tests."""
    observed_at = datetime(2026, 4, 25, 16, 0, tzinfo=UTC)
    return [
        AcquiredNodeState(
            source_id="WTG_01",
            node_key="TotW",
            value="1200.0",
            observed_at=observed_at,
        ),
        AcquiredNodeState(
            source_id="WTG_01",
            node_key="Spd",
            value="9.5",
            observed_at=observed_at,
        ),
    ]


def _read_csv_rows(path: Path) -> list[dict[str, str]]:
    """Read one CSV file into Python dictionaries."""
    with path.open("r", encoding="utf-8", newline="") as input_file:
        return list(csv.DictReader(input_file))


def test_store_many_for_mode_writes_incremental_records_to_three_files(
    tmp_path: Path,
) -> None:
    """Append acquired states to read, polling, and subscription capture files."""
    repository = FileSourceStateCache(tmp_path)
    states = _build_states()

    assert repository.store_many_for_mode("ONCE", "model_1", states) == 2
    assert repository.store_many_for_mode("POLLING", "model_1", states) == 2
    assert repository.store_many_for_mode("SUBSCRIPTION", "model_1", states) == 2

    read_records = _read_csv_rows(tmp_path / "read-results.csv")
    polling_records = _read_csv_rows(tmp_path / "polling-results.csv")
    subscription_records = _read_csv_rows(tmp_path / "subscription-results.csv")

    assert [record["id"] for record in read_records] == ["1", "2"]
    assert [record["id"] for record in polling_records] == ["1", "2"]
    assert [record["id"] for record in subscription_records] == ["1", "2"]
    assert [record["device_code"] for record in read_records] == ["WTG_01", "WTG_01"]
    assert [record["model_id"] for record in polling_records] == ["model_1", "model_1"]
    assert [record["model_id"] for record in subscription_records] == ["model_1", "model_1"]
    assert [record["variable_key"] for record in read_records] == ["TotW", "Spd"]
    assert all(record["source_observed_at"] for record in read_records)
    assert all(record["received_at"] for record in read_records)
    assert all(record["updated_at"] for record in read_records)


def test_store_many_defaults_to_read_results_file(tmp_path: Path) -> None:
    """Write default store calls into the read-results capture file."""
    repository = FileSourceStateCache(tmp_path)

    assert repository.store_many("model_1", _build_states()) == 2

    read_records = _read_csv_rows(tmp_path / "read-results.csv")
    assert [record["device_code"] for record in read_records] == ["WTG_01", "WTG_01"]


def test_test_side_cleanup_can_delete_old_capture_files_before_new_writes(
    tmp_path: Path,
) -> None:
    """Show that tests can clear stale CSV outputs before creating the repository."""
    stale_path = tmp_path / "read-results.csv"
    stale_path.write_text("stale,data\n", encoding="utf-8")
    stale_path.unlink()

    repository = FileSourceStateCache(tmp_path)

    assert repository.store_many("model_1", _build_states()) == 2
    assert repository.store_many("model_1", _build_states()) == 2

    read_records = _read_csv_rows(stale_path)
    assert [record["id"] for record in read_records] == ["1", "2", "3", "4"]
    assert [record["variable_key"] for record in read_records] == [
        "TotW",
        "Spd",
        "TotW",
        "Spd",
    ]


def test_store_many_for_mode_rejects_unknown_mode(tmp_path: Path) -> None:
    """Reject unsupported capture modes to keep output routing explicit."""
    repository = FileSourceStateCache(tmp_path)

    with pytest.raises(ValueError, match="Unsupported acquisition mode"):
        repository.store_many_for_mode("UNKNOWN", "model_1", _build_states())
