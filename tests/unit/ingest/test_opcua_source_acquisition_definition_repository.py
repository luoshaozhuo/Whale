"""Unit tests for the OPC UA acquisition-definition repository."""

from __future__ import annotations

from collections.abc import Generator
from contextlib import contextmanager

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from whale.ingest.adapters.config.opcua_source_acquisition_definition_repository import (
    OpcUaSourceAcquisitionDefinitionRepository,
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
from whale.ingest.usecases.dtos.source_runtime_config_data import (
    SourceRuntimeConfigData,
)


@contextmanager
def _session_factory() -> Generator[Session, None, None]:
    """Yield one in-memory SQLAlchemy session for repository tests."""
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)()
    try:
        substation = SubstationORM(name="S1", enabled=True)
        session.add(substation)
        session.flush()
        device = DeviceORM(
            substation_id=int(substation.id),
            device_code="WTG_01",
            device_model="WTG",
            line_number="L1",
            enabled=True,
        )
        session.add(device)
        session.flush()
        session.add(
            AcquisitionTaskORM(
                device_id=int(device.id),
                model_id="M1",
                model_version="v1",
                acquisition_mode="ONCE",
                interval_ms=0,
                endpoint="opc.tcp://127.0.0.1:4840",
                connection_params={"security_policy": "None", "security_mode": "None"},
                enabled=True,
            )
        )
        model = AcquisitionModelORM(
            model_id="M1",
            model_version="v1",
            protocol="opcua",
            model_params={"namespace_uri": "urn:windfarm:2wtg"},
        )
        session.add(model)
        session.flush()
        session.add_all(
            [
                AcquisitionVariableORM(
                    model_id=int(model.id),
                    variable_key="TotW",
                    locator="s={device_code}.TotW",
                    locator_type="node_path",
                    variable_params={},
                    display_name="Total Power",
                    enabled=True,
                    sort_order=20,
                ),
                AcquisitionVariableORM(
                    model_id=int(model.id),
                    variable_key="Spd",
                    locator="s={device_code}.Spd",
                    locator_type="node_path",
                    variable_params={},
                    display_name="Rotor Speed",
                    enabled=True,
                    sort_order=10,
                ),
                AcquisitionVariableORM(
                    model_id=int(model.id),
                    variable_key="WS",
                    locator="s={device_code}.WS",
                    locator_type="node_path",
                    variable_params={},
                    display_name="Wind Speed",
                    enabled=False,
                    sort_order=30,
                ),
            ]
        )
        session.commit()
        yield session
    finally:
        session.close()
        engine.dispose()


@contextmanager
def _repository_session_factory() -> Generator[Session, None, None]:
    """Wrap the in-memory session factory in the repository contract shape."""
    with _session_factory() as session:
        yield session


def _get_task_id(session: Session) -> int:
    """Return the only seeded acquisition-task identifier."""
    task_id = session.scalar(select(AcquisitionTaskORM.id).order_by(AcquisitionTaskORM.id))
    assert task_id is not None
    return int(task_id)


def test_get_config_builds_request_shape_from_orm_rows() -> None:
    """Build one acquisition config by joining runtime, connection and bindings."""
    repository = OpcUaSourceAcquisitionDefinitionRepository(
        session_factory=_repository_session_factory
    )

    with _repository_session_factory() as session:
        runtime_config_id = _get_task_id(session)

    definition = repository.get_config(
        SourceRuntimeConfigData(
            runtime_config_id=runtime_config_id,
            source_id="WTG_01",
            protocol="opcua",
            acquisition_mode="ONCE",
            interval_ms=0,
            enabled=True,
        )
    )

    assert definition.model_id == "M1"
    assert definition.connection.endpoint == "opc.tcp://127.0.0.1:4840"
    assert definition.connection.params["security_policy"] == "None"
    assert definition.connection.params["namespace_uri"] == "urn:windfarm:2wtg"
    assert [item.key for item in definition.items] == ["Spd", "TotW"]
    assert definition.items[0].locator == "s=WTG_01.Spd"


def test_get_config_uses_enabled_bindings_only() -> None:
    """Return only enabled items from the explicit source-item binding table."""
    repository = OpcUaSourceAcquisitionDefinitionRepository(
        session_factory=_repository_session_factory
    )

    with _repository_session_factory() as session:
        runtime_config_id = _get_task_id(session)

    definition = repository.get_config(
        SourceRuntimeConfigData(
            runtime_config_id=runtime_config_id,
            source_id="WTG_01",
            protocol="opcua",
            acquisition_mode="ONCE",
            interval_ms=0,
            enabled=True,
        )
    )

    assert [item.display_name for item in definition.items] == [
        "Rotor Speed",
        "Total Power",
    ]
    assert definition.connection.params["namespace_uri"] == "urn:windfarm:2wtg"
    assert all(item.params == {} for item in definition.items)
    assert all(item.locator.startswith("s=WTG_01.") for item in definition.items)


def test_get_config_raises_when_source_has_no_enabled_binding() -> None:
    """Raise LookupError when the source has no enabled acquisition items."""
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)()
    try:
        substation = SubstationORM(name="S2", enabled=True)
        session.add(substation)
        session.flush()
        device = DeviceORM(
            substation_id=int(substation.id),
            device_code="WTG_02",
            device_model="WTG",
            line_number="L2",
            enabled=True,
        )
        session.add(device)
        session.flush()
        session.add(
            AcquisitionTaskORM(
                device_id=int(device.id),
                model_id="M2",
                model_version="v1",
                acquisition_mode="ONCE",
                interval_ms=0,
                endpoint="opc.tcp://127.0.0.1:4840",
                connection_params={"security_policy": "None", "security_mode": "None"},
                enabled=True,
            )
        )
        model = AcquisitionModelORM(
            model_id="M2",
            model_version="v1",
            protocol="opcua",
            model_params={"namespace_uri": "urn:windfarm:2wtg"},
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
                display_name="Total Power",
                enabled=False,
                sort_order=10,
            )
        )
        session.commit()

        @contextmanager
        def _local_factory() -> Generator[Session, None, None]:
            try:
                yield session
            finally:
                pass

        repository = OpcUaSourceAcquisitionDefinitionRepository(session_factory=_local_factory)

        runtime_config_id = int(
            session.scalar(
                select(AcquisitionTaskORM.id).where(AcquisitionTaskORM.device_id == device.id)
            )
        )

        try:
            repository.get_config(
                SourceRuntimeConfigData(
                    runtime_config_id=runtime_config_id,
                    source_id="WTG_02",
                    protocol="opcua",
                    acquisition_mode="ONCE",
                    interval_ms=0,
                    enabled=True,
                )
            )
        except LookupError as exc:
            assert str(exc) == (
                "No enabled acquisition variables were found for " "model `M2` version `v1`."
            )
        else:
            raise AssertionError("Expected LookupError when variables are all disabled.")
    finally:
        session.close()
        engine.dispose()
