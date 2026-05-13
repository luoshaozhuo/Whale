"""Integration tests for framework database initialization."""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import create_engine, inspect
from sqlalchemy.engine import Engine

from whale.ingest.framework.persistence import init_db as init_db_module


def _create_sqlite_engine(database_path: Path) -> Engine:
    """Create a SQLite engine bound to the provided temporary file path.

    Args:
        database_path: SQLite file path used only by the current test.

    Returns:
        SQLAlchemy engine connected to the temporary SQLite database.
    """
    return create_engine(f"sqlite:///{database_path}")


@pytest.mark.integration
def test_init_db_creates_all_framework_tables(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Create framework ORM tables against a temporary SQLite database."""
    database_path = tmp_path / "framework.sqlite"
    engine = _create_sqlite_engine(database_path)
    monkeypatch.setattr(init_db_module, "engine", engine)
    monkeypatch.setattr("builtins.input", lambda _: "n")

    assert inspect(engine).get_table_names() == []

    init_db_module.init_db()
    init_db_module.init_db()

    inspector = inspect(engine)
    table_names = set(inspector.get_table_names())
    view_names = set(inspector.get_view_names())
    # After unification: shared ORM tables replace old ingest ORM tables
    assert "acq_task" in table_names, f"acq_task missing from {sorted(table_names)}"
    assert "acq_signal_state" in table_names
    assert "acq_signal_sample" in table_names
    assert "asset_instance" in table_names
    assert "scada_ied" in table_names
    assert "scada_ld_signal_override" not in table_names
    assert "v_scada_server" in view_names
    primary_key = inspector.get_pk_constraint("acq_task")
    assert primary_key["constrained_columns"] == ["task_id"]

    server_view_columns = [column["name"] for column in inspector.get_columns("v_scada_server")]
    assert server_view_columns == [
        "endpoint_id",
        "ied_id",
        "ld_instance_id",
        "ied_name",
        "asset_code",
        "asset_name",
        "access_point_name",
        "application_protocol",
        "transport",
        "host",
        "port",
        "namespace_uri",
        "security_policy",
        "security_mode",
        "auth_type",
        "credential_ref",
        "asset_instance_id",
        "signal_profile_id",
        "ld_name",
        "path_prefix",
    ]
