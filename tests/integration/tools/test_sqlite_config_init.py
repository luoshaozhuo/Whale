"""Integration tests for the SQLite config initialization script."""

from __future__ import annotations

import os
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest


@pytest.mark.integration
def test_sqlite_config_init_script_creates_db_from_default_templates(
    tmp_path: Path,
) -> None:
    """Run the init script through `python -m` and verify the SQLite output."""
    db_path = tmp_path / "ingest.sqlite"

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "whale.ingest.framework.persistence.init_db",
            "--non-interactive",
            "--sample-data",
        ],
        capture_output=True,
        text=True,
        check=False,
        env={
            **os.environ,
            "PYTHONPATH": str(Path.cwd() / "src"),
            "WHALE_INGEST_DB_PATH": str(db_path),
        },
    )

    assert result.returncode == 0, result.stderr
    assert "已完成初始化。" in result.stdout

    with sqlite3.connect(db_path) as conn:
        substation_count = conn.execute("SELECT COUNT(*) FROM substation").fetchone()
        device_count = conn.execute("SELECT COUNT(*) FROM device").fetchone()
        model_count = conn.execute("SELECT COUNT(*) FROM acquisition_model").fetchone()
        variable_count = conn.execute("SELECT COUNT(*) FROM acquisition_variable").fetchone()
        task_count = conn.execute("SELECT COUNT(*) FROM acquisition_task").fetchone()

    assert substation_count is not None and int(substation_count[0]) == 1
    assert device_count is not None and int(device_count[0]) == 2
    assert model_count is not None and int(model_count[0]) == 1
    assert variable_count is not None and int(variable_count[0]) == 3
    assert task_count is not None and int(task_count[0]) == 2
