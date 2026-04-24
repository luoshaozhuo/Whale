"""Database initialization entrypoint for the ingest framework."""

from __future__ import annotations

from importlib import import_module
from pathlib import Path

from sqlalchemy import inspect

from whale.ingest.config import CONFIG
from whale.ingest.framework.persistence.base import Base
from whale.ingest.framework.persistence.sample_data_loader import load_sample_data
from whale.ingest.framework.persistence.session import engine, session_scope


def init_db() -> None:
    """Create ORM tables and optionally load sample data."""
    import_module("whale.ingest.framework.persistence.orm")

    if _has_existing_schema():
        confirmation = input(_build_delete_confirmation_prompt()).strip()
        if confirmation != "delete":
            print("已取消初始化。")
            return
        _clear_existing_storage()

    insert_sample_data = input("是否插入样例数据？(y/n)：").strip().lower()

    Base.metadata.create_all(bind=engine)
    if insert_sample_data == "y":
        with session_scope() as session:
            load_sample_data(
                session=session,
                connection_config_path=_resolve_repo_path(
                    CONFIG.opcua.connection_config_path,
                ),
                nodeset_path=_resolve_repo_path(CONFIG.opcua.nodeset_path),
            )
    print("已完成初始化。")


def _resolve_database_path() -> Path:
    """Return the concrete SQLite database path."""
    database = CONFIG.database.database
    database_path = Path(database)
    if not database_path.is_absolute():
        database_path = (Path(__file__).resolve().parents[5] / database_path).resolve()
    return database_path


def _has_existing_schema() -> bool:
    """Return whether the current configured database already contains tables."""
    inspector = inspect(engine)
    return bool(inspector.get_table_names())


def _clear_existing_storage() -> None:
    """Remove existing stored schema for the configured database."""
    if CONFIG.database.drivername.startswith("sqlite"):
        database_path = _resolve_database_path()
        engine.dispose()
        if database_path.exists():
            database_path.unlink()
        return

    raise RuntimeError(
        "Automatic database deletion is only supported for sqlite. "
        "Please clear the configured non-sqlite database manually."
    )


def _storage_display_name() -> str:
    """Return a user-facing description of the configured storage target."""
    if CONFIG.database.drivername.startswith("sqlite"):
        return f"Database at {_resolve_database_path()}"
    return f"Database {CONFIG.database.drivername}://{CONFIG.database.database}"


def _build_delete_confirmation_prompt() -> str:
    """Return the localized delete confirmation prompt."""
    if CONFIG.database.drivername.startswith("sqlite"):
        return (
            f"{_storage_display_name()} 已包含数据表。"
            "此操作会永久删除当前整个数据库文件及其中的所有数据。"
            '输入 "delete" 后才会继续删除并重建：'
        )

    return (
        f"{_storage_display_name()} 已包含数据表。"
        "当前不会自动删除非 sqlite 数据库。"
        '如仍要继续确认流程，请输入 "delete"：'
    )


def _resolve_repo_path(path_value: str) -> Path:
    """Return an absolute repository path from one configured relative path."""
    return (Path(__file__).resolve().parents[5] / path_value).resolve()


if __name__ == "__main__":
    init_db()
