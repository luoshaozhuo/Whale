"""Database initialization entrypoint for the shared persistence layer."""

from __future__ import annotations

import argparse
from importlib import import_module

from sqlalchemy import inspect, text

from whale.shared.persistence import Base
from whale.shared.persistence.session import _db_url, engine


def init_db(force: bool = False) -> None:
    if force:
        reset_db()
        initialize_db()
        print("初始化完成。")
        return

    if _has_existing_schema():
        confirmation = input(_build_delete_confirmation_prompt()).strip()
        if confirmation != "delete":
            print("已取消初始化。")
            return
        reset_db()

    initialize_db()
    print("初始化完成。")


def initialize_db() -> None:
    import_module("whale.shared.persistence.orm")
    Base.metadata.create_all(bind=engine)


def reset_db() -> None:
    import_module("whale.shared.persistence.orm")

    with engine.begin() as conn:
        if _db_url.get_dialect().name == "postgresql":
            views = conn.execute(text(
                "SELECT table_name FROM information_schema.views "
                "WHERE table_schema = 'public'"
            )).fetchall()
            for (v,) in views:
                if v.startswith("v_"):
                    conn.execute(text(f"DROP VIEW IF EXISTS {v} CASCADE"))
    Base.metadata.drop_all(bind=engine)

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
    parser.add_argument("--reset", action="store_true")
    parser.add_argument("--non-interactive", action="store_true")
    parser.add_argument("--force", action="store_true")
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
    print("初始化完成。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
