"""Unit tests for the runtime-config repository."""

from __future__ import annotations

from collections.abc import Generator
from contextlib import contextmanager

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from whale.ingest.adapters.config.source_runtime_config_repository import (
    SourceRuntimeConfigRepository,
)
from whale.ingest.framework.persistence.base import Base
from whale.ingest.framework.persistence.orm.acquisition_model_orm import (
    AcquisitionModelORM,
)
from whale.ingest.framework.persistence.orm.acquisition_task_orm import (
    AcquisitionTaskORM,
)
from whale.ingest.framework.persistence.orm.acquisition_variable_orm import (
    AcquisitionVariableORM,
)
from whale.ingest.framework.persistence.orm.device_orm import DeviceORM
from whale.ingest.framework.persistence.orm.substation_orm import SubstationORM


@contextmanager
def _session_factory() -> Generator[Session, None, None]:
    """Yield one in-memory SQLAlchemy session for runtime-config tests."""
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)()
    try:
        substation = SubstationORM(name="S1", enabled=True)
        session.add(substation)
        session.flush()
        first_device = DeviceORM(
            substation_id=int(substation.id),
            device_code="WTG_01",
            device_model="WTG",
            line_number="L1",
            enabled=True,
        )
        second_device = DeviceORM(
            substation_id=int(substation.id),
            device_code="WTG_02",
            device_model="WTG",
            line_number="L1",
            enabled=True,
        )
        session.add_all([first_device, second_device])
        model = AcquisitionModelORM(
            model_id="M1",
            model_version="v1",
            protocol="opcua",
        )
        session.add(model)
        session.flush()
        session.add(
            AcquisitionVariableORM(
                model_id=int(model.id),
                variable_key="TotW",
                locator="s={device_code}.TotW",
                locator_type="node_path",
                variable_params={},
                sort_order=0,
                enabled=True,
            )
        )
        session.flush()
        session.add_all(
            [
                AcquisitionTaskORM(
                    device_id=int(first_device.id),
                    model_id="M1",
                    model_version="v1",
                    acquisition_mode="ONCE",
                    interval_ms=0,
                    enabled=True,
                ),
                AcquisitionTaskORM(
                    device_id=int(second_device.id),
                    model_id="M1",
                    model_version="v1",
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


def test_runtime_config_id_is_independent_from_source_id() -> None:
    """Expose the new schema rule that runtime-config id is a separate key."""
    repository = SourceRuntimeConfigRepository(session_factory=_session_factory)

    config = repository.list_enabled()[0]

    assert isinstance(config.runtime_config_id, int)
    assert config.runtime_config_id != config.source_id
