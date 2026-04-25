"""File-backed variable-state repository for ingest testing."""

from __future__ import annotations

import csv
from datetime import UTC, datetime
from pathlib import Path
from threading import Lock

from whale.ingest.ports.store.source_state_store_port import (
    ModeAwareSourceStateStorePort,
)
from whale.ingest.usecases.dtos.acquired_node_state import AcquiredNodeState

READ_MODE = "ONCE"
POLLING_MODE = "POLLING"
SUBSCRIPTION_MODE = "SUBSCRIPTION"


class FileVariableStateRepository(ModeAwareSourceStateStorePort):
    """Append acquired states into mode-specific CSV files for tests."""

    def __init__(self, output_dir: Path) -> None:
        """Create one file-backed repository rooted at the given directory."""
        self._output_dir = output_dir
        self._output_dir.mkdir(parents=True, exist_ok=True)
        self._lock = Lock()
        self._output_paths = {
            READ_MODE: self._output_dir / "read-results.csv",
            POLLING_MODE: self._output_dir / "polling-results.csv",
            SUBSCRIPTION_MODE: self._output_dir / "subscription-results.csv",
        }
        self._fieldnames = (
            "id",
            "device_code",
            "model_id",
            "variable_key",
            "value",
            "source_observed_at",
            "received_at",
            "updated_at",
        )

    def store_many(
        self,
        model_id: str,
        acquired_states: list[AcquiredNodeState],
    ) -> int:
        """Store many acquired states in the read-results file by default."""
        return self.store_many_for_mode(READ_MODE, model_id, acquired_states)

    def store_many_for_mode(
        self,
        acquisition_mode: str,
        model_id: str,
        acquired_states: list[AcquiredNodeState],
    ) -> int:
        """Append each acquired state as one CSV row in the mode-specific file."""
        output_path = self._resolve_output_path(acquisition_mode)
        received_at = datetime.now(tz=UTC).isoformat()
        if not acquired_states:
            return 0

        with self._lock:
            file_exists = output_path.exists()
            next_id = self._read_next_id(output_path) if file_exists else 1
            records = [
                {
                    "id": str(next_id + index),
                    "device_code": state.source_id,
                    "model_id": model_id,
                    "variable_key": state.node_key,
                    "value": state.value,
                    "source_observed_at": state.observed_at.isoformat(),
                    "received_at": received_at,
                    "updated_at": received_at,
                }
                for index, state in enumerate(acquired_states)
            ]
            with output_path.open("a", encoding="utf-8", newline="") as output_file:
                writer = csv.DictWriter(output_file, fieldnames=self._fieldnames)
                if not file_exists:
                    writer.writeheader()
                writer.writerows(records)
        return len(records)

    def _resolve_output_path(self, acquisition_mode: str) -> Path:
        """Return the file used to capture results for the given acquisition mode."""
        try:
            return self._output_paths[acquisition_mode]
        except KeyError as exc:
            raise ValueError(
                f"Unsupported acquisition mode for file capture: {acquisition_mode}"
            ) from exc

    def _read_next_id(self, output_path: Path) -> int:
        """Return the next surrogate identifier for the target CSV file."""
        with output_path.open("r", encoding="utf-8", newline="") as input_file:
            rows = list(csv.DictReader(input_file))
        if not rows:
            return 1
        return int(rows[-1]["id"]) + 1
