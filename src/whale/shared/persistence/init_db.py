"""Database initialization entrypoint for the shared persistence layer."""

from __future__ import annotations

import argparse
from importlib import import_module

from sqlalchemy import inspect, text

from whale.shared.persistence import Base
from whale.shared.persistence.orm.asset import WIND_TURBINE_BOM_VIEW_SQL
from whale.shared.persistence.orm.scada_model import MEASUREMENT_POINT_VIEW_SQL
from whale.shared.persistence.session import _db_url, engine, session_scope


def init_db() -> None:
    """Create all shared ORM tables and the measurement-point view."""
    if _has_existing_schema():
        confirmation = input(_build_delete_confirmation_prompt()).strip()
        if confirmation != "delete":
            print("已取消初始化。")
            return
        reset_db()

    initialize_db()
    print("已完成初始化。")


def initialize_db() -> None:
    """Create tables from all shared ORM models, then create the DA view."""
    import_module("whale.shared.persistence.orm")
    Base.metadata.create_all(bind=engine)

    with engine.connect() as conn:
        # 防止之前版本把 v_measurement_point 建成了表
        for view_sql in (WIND_TURBINE_BOM_VIEW_SQL, MEASUREMENT_POINT_VIEW_SQL):
            # "CREATE VIEW IF NOT EXISTS <name> AS ..."
            # "CREATE VIEW IF NOT EXISTS <name> AS ..." → name is word #5
            view_name = view_sql.strip().split()[5]
            conn.execute(text(f"DROP TABLE IF EXISTS {view_name}"))
            conn.execute(text(f"DROP VIEW IF EXISTS {view_name}"))
            conn.execute(text(view_sql))
        conn.commit()


def reset_db() -> None:
    """Drop all tables and remove the view."""
    import_module("whale.shared.persistence.orm")

    if _db_url.get_dialect().name == "sqlite":
        engine.dispose()

    with engine.begin() as conn:
        conn.execute(text("DROP VIEW IF EXISTS v_measurement_point"))
    Base.metadata.drop_all(bind=engine)

    # SQLite: also delete the file for a truly clean slate
    if _db_url.get_dialect().name == "sqlite":
        from pathlib import Path

        db_path = Path(str(_db_url.database))
        if db_path.exists():
            db_path.unlink()


def _has_existing_schema() -> bool:
    inspector = inspect(engine)
    return bool(inspector.get_table_names())


def _build_delete_confirmation_prompt() -> str:
    return (
        f"数据库 {_db_url} 已包含数据表。"
        "此操作会清除所有数据并重建。"
        '输入 "delete" 后才会继续删除并重建：'
    )


def _build_argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Initialize the shared persistence database.")
    parser.add_argument(
        "--reset",
        action="store_true",
        help="Delete existing database before re-initializing.",
    )
    parser.add_argument(
        "--non-interactive",
        action="store_true",
        help="Run without interactive prompts.",
    )
    return parser


def main() -> int:
    args = _build_argument_parser().parse_args()

    if args.reset:
        reset_db()
    elif not args.non_interactive:
        init_db()
        return 0

    initialize_db()
    print("已完成初始化。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
