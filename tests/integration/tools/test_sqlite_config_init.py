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
        org_count = conn.execute("SELECT COUNT(*) FROM org_unit").fetchone()
        asset_count = conn.execute("SELECT COUNT(*) FROM asset_instance").fetchone()
        ied_count = conn.execute("SELECT COUNT(*) FROM scada_ied").fetchone()
        item_count = conn.execute("SELECT COUNT(*) FROM scada_signal_profile_item").fetchone()
        task_count = conn.execute("SELECT COUNT(*) FROM acq_task").fetchone()

    assert org_count is not None and int(org_count[0]) >= 1
    assert asset_count is not None and int(asset_count[0]) >= 30
    assert ied_count is not None and int(ied_count[0]) >= 1
    assert item_count is not None and int(item_count[0]) > 0
    assert task_count is not None and int(task_count[0]) >= 30
