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
from whale.ingest.framework.persistence.orm.opcua_connection_orm import (
    OpcUaClientConnectionORM,
)
from whale.ingest.framework.persistence.orm.opcua_source_item_binding_orm import (
    OpcUaSourceItemBindingORM,
)
from whale.ingest.framework.persistence.orm.source_runtime_config_orm import (
    SourceRuntimeConfigORM,
)


@contextmanager
def _session_factory() -> Generator[Session, None, None]:
    """Yield one in-memory SQLAlchemy session for repository tests."""
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)()
    try:
        runtime_config = SourceRuntimeConfigORM(
            source_id="WTG_01",
            protocol="opcua",
            acquisition_mode="ONCE",
            interval_ms=0,
            enabled=True,
        )
        session.add(runtime_config)
        session.add(
            OpcUaClientConnectionORM(
                name="WTG_01",
                endpoint="opc.tcp://127.0.0.1:4840",
                security_policy="None",
                security_mode="None",
                update_interval_ms=100,
                enabled=True,
            )
        )
        session.flush()
        session.add_all(
            [
                OpcUaSourceItemBindingORM(
                    source_id="WTG_01",
                    item_key="TotW",
                    node_address="s=WTG_01.TotW",
                    namespace_uri="urn:windfarm:2wtg",
                    display_name="Total Power",
                    enabled=True,
                    sort_order=20,
                ),
                OpcUaSourceItemBindingORM(
                    source_id="WTG_01",
                    item_key="Spd",
                    node_address="s=WTG_01.Spd",
                    namespace_uri="urn:windfarm:2wtg",
                    display_name="Rotor Speed",
                    enabled=True,
                    sort_order=10,
                ),
                OpcUaSourceItemBindingORM(
                    source_id="WTG_01",
                    item_key="WS",
                    node_address="s=WTG_01.WS",
                    namespace_uri="urn:windfarm:2wtg",
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


def test_get_read_once_definition_builds_request_shape_from_orm_rows() -> None:
    """Build one acquisition definition by joining runtime, connection and bindings."""
    repository = OpcUaSourceAcquisitionDefinitionRepository(
        session_factory=_repository_session_factory
    )

    with _repository_session_factory() as session:
        runtime_config_id = int(
            session.scalar(
                select(SourceRuntimeConfigORM.id).where(
                    SourceRuntimeConfigORM.source_id == "WTG_01"
                )
            )
        )

    definition = repository.get_read_once_definition(runtime_config_id)

    assert definition.runtime_config_id == runtime_config_id
    assert definition.source_id == "WTG_01"
    assert definition.connection.endpoint == "opc.tcp://127.0.0.1:4840"
    assert [item.key for item in definition.items] == ["Spd", "TotW"]
    assert definition.items[0].address == "s=WTG_01.Spd"


def test_get_read_once_definition_uses_enabled_bindings_only() -> None:
    """Return only enabled items from the explicit source-item binding table."""
    repository = OpcUaSourceAcquisitionDefinitionRepository(
        session_factory=_repository_session_factory
    )

    with _repository_session_factory() as session:
        runtime_config_id = int(
            session.scalar(
                select(SourceRuntimeConfigORM.id).where(
                    SourceRuntimeConfigORM.source_id == "WTG_01"
                )
            )
        )

    definition = repository.get_read_once_definition(runtime_config_id)

    assert [item.display_name for item in definition.items] == [
        "Rotor Speed",
        "Total Power",
    ]
    assert all(item.namespace_uri == "urn:windfarm:2wtg" for item in definition.items)
    assert all(item.address.startswith("s=WTG_01.") for item in definition.items)


def test_get_read_once_definition_raises_when_source_has_no_enabled_binding() -> None:
    """Raise LookupError when the source has no enabled acquisition items."""
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)()
    try:
        runtime_config = SourceRuntimeConfigORM(
            source_id="WTG_02",
            protocol="opcua",
            acquisition_mode="ONCE",
            interval_ms=0,
            enabled=True,
        )
        session.add(runtime_config)
        session.add(
            OpcUaClientConnectionORM(
                name="WTG_02",
                endpoint="opc.tcp://127.0.0.1:4840",
                security_policy="None",
                security_mode="None",
                update_interval_ms=100,
                enabled=True,
            )
        )
        session.add(
            OpcUaSourceItemBindingORM(
                source_id="WTG_02",
                item_key="TotW",
                node_address="s=WTG_02.TotW",
                namespace_uri="urn:windfarm:2wtg",
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

        runtime_config_id = int(runtime_config.id)

        try:
            repository.get_read_once_definition(runtime_config_id)
        except LookupError as exc:
            assert str(exc) == "No enabled item bindings were found for source `WTG_02`."
        else:
            raise AssertionError("Expected LookupError when bindings are all disabled.")
    finally:
        session.close()
        engine.dispose()
