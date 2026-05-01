"""Database initialization entrypoint for the shared persistence layer."""

from __future__ import annotations

import argparse
from importlib import import_module

from sqlalchemy import inspect, text

from whale.shared.persistence import Base
from whale.shared.persistence.orm.asset import WIND_TURBINE_BOM_VIEW_SQL
from whale.shared.persistence.orm.scada_model import (
    ACQ_DO_STATE_DETAIL_VIEW_SQL,
    ASSET_MODEL_DETAIL_VIEW_SQL,
    COMPONENT_MODEL_DETAIL_VIEW_SQL,
    MEASUREMENT_POINT_VIEW_SQL,
)
from whale.shared.persistence.session import _db_url, engine


def init_db(force: bool = False) -> None:
    """Create all shared ORM tables and views.

    Args:
        force: If True, delete existing database without confirmation.
    """
    if force:
        reset_db()
        initialize_db()
        print("已完成强制初始化。")
        return

    if _has_existing_schema():
        confirmation = input(_build_delete_confirmation_prompt()).strip()
        if confirmation != "delete":
            print("已取消初始化。")
            return
        reset_db()

    initialize_db()
    print("已完成初始化。")


def initialize_db() -> None:
    """Create tables from all shared ORM models, then create views."""
    import_module("whale.shared.persistence.orm")
    Base.metadata.create_all(bind=engine)

    with engine.connect() as conn:
        for view_sql in (
            WIND_TURBINE_BOM_VIEW_SQL,
            MEASUREMENT_POINT_VIEW_SQL,
            ASSET_MODEL_DETAIL_VIEW_SQL,
            COMPONENT_MODEL_DETAIL_VIEW_SQL,
            ACQ_DO_STATE_DETAIL_VIEW_SQL,
        ):
            view_name = view_sql.strip().split()[5]
            conn.execute(text(f"DROP TABLE IF EXISTS {view_name}"))
            conn.execute(text(f"DROP VIEW IF EXISTS {view_name}"))
            # Fix SQLite-specific syntax for PostgreSQL
            sql = view_sql.replace("IF NOT EXISTS ", "")
            if _db_url.get_dialect().name == "postgresql":
                import re
                # json_extract → PostgreSQL ->> operator
                sql = re.sub(
                    r"json_extract\((\w+\.specifications),\s*'\$\.'\s*\|\|\s*(\w+\.attribute_name)\)",
                    r"\1 ->> \2",
                    sql,
                )
                # "do" is a reserved keyword in PostgreSQL, rename alias
                sql = re.sub(r"\bscada_do\s+do\b", "scada_do        d", sql)
                sql = re.sub(r"\bdo\.", "d.", sql)
            conn.execute(text(sql))

        conn.commit()


def reset_db() -> None:
    """Drop all tables and remove views."""
    import_module("whale.shared.persistence.orm")

    with engine.begin() as conn:
        # Drop known views first to avoid dependency issues
        for v in ("v_measurement_point", "v_wind_turbine_bom",
                   "v_asset_model_detail", "v_component_model_detail",
                   "v_acq_do_state_detail"):
            conn.execute(text(f"DROP VIEW IF EXISTS {v}"))
    Base.metadata.drop_all(bind=engine)

    # Dispose and delete file last, after all DB operations complete
    if _db_url.get_dialect().name == "sqlite":
        engine.dispose()
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
    parser.add_argument(
        "--force",
        action="store_true",
        help="Force delete existing database without confirmation.",
    )
    return parser


def main() -> int:
    args = _build_argument_parser().parse_args()

    if args.force:
        init_db(force=True)
        return 0
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
