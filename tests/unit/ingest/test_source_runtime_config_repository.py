"""Unit tests for the runtime-config repository."""

from __future__ import annotations

from collections.abc import Generator
from contextlib import contextmanager

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from whale.ingest.adapters.config.source_runtime_config_repository import (
    SourceRuntimeConfigRepository,
)
from whale.ingest.framework.persistence.base import Base
from whale.ingest.framework.persistence.orm.source_runtime_config_orm import (
    SourceRuntimeConfigORM,
)


@contextmanager
def _session_factory() -> Generator[Session, None, None]:
    """Yield one in-memory SQLAlchemy session for runtime-config tests."""
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)()
    try:
        session.add_all(
            [
                SourceRuntimeConfigORM(
                    source_id="WTG_01",
                    protocol="opcua",
                    acquisition_mode="ONCE",
                    interval_ms=0,
                    enabled=True,
                ),
                SourceRuntimeConfigORM(
                    source_id="WTG_02",
                    protocol="opcua",
                    acquisition_mode="ONCE",
                    interval_ms=1000,
                    enabled=False,
                ),
            ]
        )
        session.commit()
        yield session
    finally:
        session.close()
        engine.dispose()


def test_list_enabled_returns_enabled_runtime_rows_only() -> None:
    """Return only enabled runtime config rows."""
    repository = SourceRuntimeConfigRepository(session_factory=_session_factory)

    configs = repository.list_enabled()

    assert len(configs) == 1
    assert isinstance(configs[0].runtime_config_id, int)
    assert configs[0].source_id == "WTG_01"


def test_get_by_id_returns_runtime_config_data() -> None:
    """Return one runtime config by its runtime-config id."""
    with _session_factory() as session:
        runtime_config_id = int(
            session.scalar(
                select(SourceRuntimeConfigORM.id).where(
                    SourceRuntimeConfigORM.source_id == "WTG_02"
                )
            )
        )

    repository = SourceRuntimeConfigRepository(session_factory=_session_factory)

    config = repository.get_by_id(runtime_config_id)

    assert config.runtime_config_id == runtime_config_id
    assert config.source_id == "WTG_02"
    assert config.interval_ms == 1000
    assert config.enabled is False


def test_runtime_config_id_is_independent_from_source_id() -> None:
    """Expose the new schema rule that runtime-config id is a separate key."""
    repository = SourceRuntimeConfigRepository(session_factory=_session_factory)

    config = repository.list_enabled()[0]

    assert isinstance(config.runtime_config_id, int)
    assert config.runtime_config_id != config.source_id
