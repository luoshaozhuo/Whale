"""Integration tests for the ingest runtime."""

from __future__ import annotations

import os
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest
import yaml
from sqlalchemy import create_engine

import whale.ingest.framework.persistence.orm as ingest_orm
from tools.opcua_sim.server_runtime import OpcUaServerRuntime, load_server_config
from whale.ingest.framework.persistence.base import Base


def _create_ingest_database(database_path: Path) -> None:
    """Create the ingest schema in the provided SQLite database path."""
    assert ingest_orm.__all__
    engine = create_engine(f"sqlite:///{database_path}")
    Base.metadata.create_all(bind=engine)
    engine.dispose()


def _seed_runtime_connection(
    database_path: Path,
    *,
    source_id: str,
    endpoint: str,
    enabled: bool = True,
    acquisition_mode: str = "ONCE",
) -> int:
    """Insert runtime config, connection config and explicit source-item bindings."""
    with sqlite3.connect(database_path) as connection:
        connection.execute(
            """
            INSERT INTO opcua_client_connections
            (name, endpoint, security_policy, security_mode, update_interval_ms, enabled)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (source_id, endpoint, "None", "None", 100, 1),
        )
        connection.execute(
            """
            INSERT INTO source_runtime_config
            (source_id, protocol, acquisition_mode, interval_ms, enabled)
            VALUES (?, ?, ?, ?, ?)
            """,
            (source_id, "opcua", acquisition_mode, 0, int(enabled)),
        )
        runtime_config_id = int(connection.execute("SELECT last_insert_rowid()").fetchone()[0])
        connection.executemany(
            """
            INSERT INTO opcua_source_item_binding
            (
                source_id,
                item_key,
                node_address,
                namespace_uri,
                display_name,
                enabled,
                sort_order
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    source_id,
                    "TotW",
                    f"s={source_id}.TotW",
                    "urn:windfarm:2wtg",
                    "TotW",
                    1,
                    20,
                ),
                (
                    source_id,
                    "Spd",
                    f"s={source_id}.Spd",
                    "urn:windfarm:2wtg",
                    "Spd",
                    1,
                    10,
                ),
                (
                    source_id,
                    "WS",
                    f"s={source_id}.WS",
                    "urn:windfarm:2wtg",
                    "WS",
                    1,
                    30,
                ),
            ],
        )
        connection.commit()
    return runtime_config_id


def _run_ingest(database_path: Path) -> subprocess.CompletedProcess[str]:
    """Run the ingest entrypoint against the provided SQLite database."""
    return subprocess.run(
        [sys.executable, "-m", "whale.ingest"],
        cwd=Path.cwd(),
        capture_output=True,
        text=True,
        check=False,
        env={
            **os.environ,
            "PYTHONPATH": str(Path.cwd() / "src"),
            "WHALE_INGEST_DB_PATH": str(database_path),
        },
    )


def _write_connection_config(tmp_path: Path, endpoint: str) -> Path:
    """Write one local OPC UA connection YAML for simulator startup."""
    path = tmp_path / "opcua-connections.yaml"
    path.write_text(
        yaml.safe_dump(
            {
                "connections": [
                    {
                        "name": "WTG_01",
                        "endpoint": endpoint,
                        "security_policy": "None",
                        "security_mode": "None",
                        "update_interval_ms": 100,
                    }
                ]
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    return path


@pytest.mark.integration
def test_python_m_whale_ingest_reads_opcua_and_persists_node_states(
    tmp_path: Path,
) -> None:
    """Run the ingest entrypoint end-to-end against one live OPC UA simulator."""
    database_path = tmp_path / "ingest.sqlite"
    _create_ingest_database(database_path)
    endpoint = "opc.tcp://127.0.0.1:4851"
    connection_config_path = _write_connection_config(tmp_path, endpoint)
    runtime_config_id = _seed_runtime_connection(
        database_path,
        source_id="WTG_01",
        endpoint=endpoint,
    )

    with OpcUaServerRuntime(
        nodeset_path="tools/opcua_sim/templates/OPCUANodeSet.xml",
        config=load_server_config(connection_config_path, "WTG_01"),
    ):
        result = _run_ingest(database_path)

    assert result.returncode == 0, result.stderr
    assert "[ingest] starting scheduler..." in result.stdout

    with sqlite3.connect(database_path) as connection:
        rows = connection.execute("""
            SELECT source_id, node_key, value
            FROM source_node_latest_state
            ORDER BY node_key
            """).fetchall()
        history_row_count = connection.execute("SELECT COUNT(*) FROM source_node_state").fetchone()

    assert [row[0] for row in rows] == ["WTG_01", "WTG_01", "WTG_01"]
    assert [row[1] for row in rows] == ["Spd", "TotW", "WS"]
    assert all(float(row[2]) > 0 for row in rows)
    assert history_row_count is not None
    assert int(history_row_count[0]) == 0
    assert f"once:{runtime_config_id}" not in result.stderr


@pytest.mark.integration
def test_python_m_whale_ingest_reports_failed_jobs_without_persisting_rows(
    tmp_path: Path,
) -> None:
    """Return a non-zero exit code when the configured endpoint is unreachable."""
    database_path = tmp_path / "ingest-failure.sqlite"
    _create_ingest_database(database_path)
    runtime_config_id = _seed_runtime_connection(
        database_path,
        source_id="WTG_01",
        endpoint="opc.tcp://127.0.0.1:1",
    )

    result = _run_ingest(database_path)

    assert result.returncode == 1
    assert f"once:{runtime_config_id}" in result.stderr
    assert "status=FAILED" in result.stderr
    assert "result_status=FAILED" in result.stderr
    assert "one or more scheduler jobs failed" in result.stderr

    with sqlite3.connect(database_path) as connection:
        row_count = connection.execute("SELECT COUNT(*) FROM source_node_latest_state").fetchone()
        history_row_count = connection.execute("SELECT COUNT(*) FROM source_node_state").fetchone()

    assert row_count is not None
    assert int(row_count[0]) == 0
    assert history_row_count is not None
    assert int(history_row_count[0]) == 0
