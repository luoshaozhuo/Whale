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
    assert table_names == {
        "acquisition_model",
        "acquisition_task",
        "acquisition_variable",
        "device",
        "state_snapshot_outbox",
        "substation",
        "variable_state",
    }
    primary_key = inspector.get_pk_constraint("variable_state")
    assert primary_key["constrained_columns"] == ["id"]
