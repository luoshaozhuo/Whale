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
    db_path = tmp_path / "opcua_config.sqlite"
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        """
database:
  drivername: sqlite
  database: {db_path}
  pool_size: 5
  max_overflow: 10
  pool_timeout: 30
  pool_recycle: 3600
  pool_pre_ping: true
opcua:
  connection_config_path: tools/opcua_sim/templates/OPCUA_client_connections.yaml
  nodeset_path: tools/opcua_sim/templates/OPCUANodeSet.xml
""".strip().format(db_path=db_path) + "\n",
        encoding="utf-8",
    )

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "whale.ingest.infrastructure.db.init_db",
            "--config-path",
            str(config_path),
        ],
        capture_output=True,
        text=True,
        check=False,
        env={
            **os.environ,
            "PYTHONPATH": str(Path.cwd() / "src"),
        },
    )

    assert result.returncode == 0, result.stderr
    assert "SQLite config initialized" in result.stdout

    with sqlite3.connect(db_path) as conn:
        connection_count = conn.execute("SELECT COUNT(*) FROM opcua_client_connections").fetchone()
        node_count = conn.execute("SELECT COUNT(*) FROM opcua_nodeset_variables").fetchone()
        reference_count = conn.execute("SELECT COUNT(*) FROM opcua_nodeset_references").fetchone()

    assert connection_count is not None and int(connection_count[0]) == 2
    assert node_count is not None and int(node_count[0]) == 3
    assert reference_count is not None and int(reference_count[0]) > 0
