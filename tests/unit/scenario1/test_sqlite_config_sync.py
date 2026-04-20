"""Unit tests for initializing OPC UA config into SQLite through the service."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
import yaml
from sqlalchemy.engine import URL

from whale.ingest.framework.db.base import (
    Base,
    build_session_factory,
    create_database_engine,
)
from whale.ingest.application.services.opcua_config_import_service import OpcUaConfigImportService
from whale.ingest.adapter.repositories.opcua_config_repository import OpcUaConfigQueryRepository


@pytest.mark.unit
def test_opcua_config_import_service_imports_template_files(
    tmp_path: Path,
    sample_opcua_connections_path: str,
    sample_nodeset_path: str,
) -> None:
    """Import the template config files into a fresh SQLite database."""
    db_path = tmp_path / "opcua_config.sqlite"
    engine = create_database_engine(URL.create(drivername="sqlite", database=str(db_path)))
    Base.metadata.create_all(engine)
    service = OpcUaConfigImportService(session_factory=build_session_factory(engine))

    result = service.import_from_files(
        connection_config_path=sample_opcua_connections_path,
        nodeset_path=sample_nodeset_path,
    )

    assert result.connections_written == 2
    assert result.variables_written == 3
    assert result.namespace_uris_written == 2
    assert result.object_types_written == 1
    assert result.objects_written == 3

    with sqlite3.connect(db_path) as conn:
        connection_count = conn.execute("SELECT COUNT(*) FROM opcua_client_connections").fetchone()
        node_count = conn.execute("SELECT COUNT(*) FROM opcua_nodeset_variables").fetchone()
        first_connection = conn.execute("""
            SELECT name, endpoint, update_interval_ms
            FROM opcua_client_connections
            ORDER BY name
            LIMIT 1
            """).fetchone()

    assert connection_count is not None and int(connection_count[0]) == 2
    assert node_count is not None and int(node_count[0]) == 3
    assert first_connection == ("WTG_01", "opc.tcp://127.0.0.1:4840", 100)


@pytest.mark.unit
def test_opcua_config_import_service_replaces_existing_rows(
    tmp_path: Path,
    sample_opcua_connections_path: str,
    sample_nodeset_path: str,
) -> None:
    """Update existing SQLite rows when the source file content changes."""
    db_path = tmp_path / "opcua_config.sqlite"
    connection_path = tmp_path / "OPCUA_client_connections.custom.yaml"
    engine = create_database_engine(URL.create(drivername="sqlite", database=str(db_path)))
    Base.metadata.create_all(engine)
    session_factory = build_session_factory(engine)
    service = OpcUaConfigImportService(session_factory=session_factory)

    config = yaml.safe_load(Path(sample_opcua_connections_path).read_text(encoding="utf-8"))
    assert isinstance(config, dict)
    connections = config.get("connections", [])
    assert isinstance(connections, list)
    assert isinstance(connections[0], dict)
    connections[0]["endpoint"] = "opc.tcp://127.0.0.1:5850"
    connections[0]["update_interval_ms"] = 500
    connection_path.write_text(yaml.safe_dump(config, sort_keys=False), encoding="utf-8")

    service.import_from_files(
        connection_config_path=sample_opcua_connections_path,
        nodeset_path=sample_nodeset_path,
    )
    service.import_from_files(
        connection_config_path=connection_path,
        nodeset_path=sample_nodeset_path,
    )

    with sqlite3.connect(db_path) as conn:
        updated_row = conn.execute("""
            SELECT endpoint, update_interval_ms
            FROM opcua_client_connections
            WHERE name = 'WTG_01'
            """).fetchone()

    assert updated_row == ("opc.tcp://127.0.0.1:5850", 500)

    query_repository = OpcUaConfigQueryRepository()
    with session_factory() as session:
        overview = query_repository.nodeset_overview(session)

    assert overview["connections"] == 2
    assert overview["variables"] == 3
