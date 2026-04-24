"""Integration tests for the ingest runtime."""

from __future__ import annotations

import json
import os
import socket
import sqlite3
import subprocess
import sys
from contextlib import closing
from pathlib import Path

import pytest
import yaml
from sqlalchemy import create_engine

import whale.ingest.framework.persistence.orm as ingest_orm
from tools.opcua_sim.server_runtime import OpcUaServerRuntime, load_server_config
from whale.ingest.framework.persistence.base import Base


def _get_free_port() -> int:
    """Return one currently available local TCP port."""
    with closing(socket.socket(socket.AF_INET, socket.SOCK_STREAM)) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


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
    """Insert one device, acquisition model and acquisition task."""
    with sqlite3.connect(database_path) as connection:
        connection.execute(
            """
            INSERT INTO substation
            (name, enabled)
            VALUES (?, ?)
            """,
            ("S1", 1),
        )
        substation_id = int(connection.execute("SELECT last_insert_rowid()").fetchone()[0])
        connection.execute(
            """
            INSERT INTO device
            (substation_id, device_code, device_model, line_number, enabled)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                substation_id,
                source_id,
                "WTG",
                "L1",
                1,
            ),
        )
        device_id = int(connection.execute("SELECT last_insert_rowid()").fetchone()[0])
        connection.execute(
            """
            INSERT INTO acquisition_model
            (model_id, model_version, protocol, model_params)
            VALUES (?, ?, ?, ?)
            """,
            ("WTG_OPCUA_DEMO", "v1", "opcua", json.dumps({"namespace_uri": "urn:windfarm:2wtg"})),
        )
        model_id = int(connection.execute("SELECT last_insert_rowid()").fetchone()[0])
        connection.execute(
            """
            INSERT INTO acquisition_task
            (
                device_id,
                model_id,
                model_version,
                acquisition_mode,
                interval_ms,
                endpoint,
                connection_params,
                enabled
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                device_id,
                "WTG_OPCUA_DEMO",
                "v1",
                acquisition_mode,
                0,
                endpoint,
                json.dumps({"security_policy": "None", "security_mode": "None"}),
                int(enabled),
            ),
        )
        runtime_config_id = int(connection.execute("SELECT last_insert_rowid()").fetchone()[0])
        connection.executemany(
            """
            INSERT INTO acquisition_variable
            (
                model_id,
                variable_key,
                locator,
                locator_type,
                variable_params,
                display_name,
                enabled,
                sort_order
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    model_id,
                    "TotW",
                    "s={device_code}.TotW",
                    "node_path",
                    json.dumps({}),
                    "TotW",
                    1,
                    20,
                ),
                (
                    model_id,
                    "Spd",
                    "s={device_code}.Spd",
                    "node_path",
                    json.dumps({}),
                    "Spd",
                    1,
                    10,
                ),
                (
                    model_id,
                    "WS",
                    "s={device_code}.WS",
                    "node_path",
                    json.dumps({}),
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
    endpoint = f"opc.tcp://127.0.0.1:{_get_free_port()}"
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
            SELECT device_code, model_id, variable_key, value
            FROM variable_state
            ORDER BY variable_key
            """).fetchall()

    assert [row[0] for row in rows] == ["WTG_01", "WTG_01", "WTG_01"]
    assert [row[1] for row in rows] == ["WTG_OPCUA_DEMO", "WTG_OPCUA_DEMO", "WTG_OPCUA_DEMO"]
    assert [row[2] for row in rows] == ["Spd", "TotW", "WS"]
    assert all(float(row[3]) > 0 for row in rows)
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
        row_count = connection.execute("SELECT COUNT(*) FROM variable_state").fetchone()

    assert row_count is not None
    assert int(row_count[0]) == 0
