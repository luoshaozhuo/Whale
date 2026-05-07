"""Unit tests for the runtime-config repository."""

from __future__ import annotations

from collections.abc import Generator
from contextlib import contextmanager

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from whale.ingest.adapters.config.source_runtime_config_repository import (
    SourceRuntimeConfigRepository,
)
from whale.shared.persistence import Base
from whale.shared.persistence.orm import (
    AssetInstance,
    AssetType,
    CommunicationEndpoint,
    IED,
    LDInstance,
    ScadaDataType,
    SignalProfile,
    SignalProfileItem,
)


@contextmanager
def _session_scope(session_factory: sessionmaker[Session]) -> Generator[Session, None, None]:
    session = session_factory()
    try:
        yield session
    finally:
        session.close()


def test_repository_lists_servers_and_profile_items() -> None:
    """Return deterministic server rows plus ordered profile items."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    session_factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)

    with _session_scope(session_factory) as session:
        asset_type = AssetType(type_code="WTG", type_name="Wind Turbine")
        session.add(asset_type)
        session.flush()

        asset = AssetInstance(
            asset_code="WTG_01",
            asset_name="WTG 01",
            asset_type_id=asset_type.asset_type_id,
        )
        session.add(asset)
        session.flush()

        signal_profile = SignalProfile(
            profile_code="WTG_PROFILE_V1",
            profile_name="WTG Profile V1",
        )
        session.add(signal_profile)
        session.flush()

        data_type = ScadaDataType(type_name="FLOAT64")
        session.add(data_type)
        session.flush()

        ied = IED(
            asset_instance_id=asset.asset_instance_id,
            ied_name="IED_WTG_01",
        )
        session.add(ied)
        session.flush()

        endpoint = CommunicationEndpoint(
            ied_id=ied.ied_id,
            access_point_name="OPCUA_AP",
            application_protocol="OPC_UA",
            transport="TCP",
            host="127.0.0.1",
            port=4840,
            namespace_uri="urn:windfarm:2wtg",
        )
        session.add(endpoint)
        session.flush()

        ld_instance = LDInstance(
            endpoint_id=endpoint.endpoint_id,
            asset_instance_id=asset.asset_instance_id,
            signal_profile_id=signal_profile.signal_profile_id,
            ld_name="WTG_01",
        )
        session.add(ld_instance)
        session.flush()

        session.add_all(
            [
                SignalProfileItem(
                    signal_profile_id=signal_profile.signal_profile_id,
                    ln_name="MMXU1",
                    do_name="TotW",
                    relative_path="MMXU1.TotW",
                    data_type_id=data_type.data_type_id,
                ),
                SignalProfileItem(
                    signal_profile_id=signal_profile.signal_profile_id,
                    ln_name="MMXU1",
                    do_name="WS",
                    relative_path="MMXU1.WS",
                    data_type_id=data_type.data_type_id,
                ),
            ]
        )
        session.commit()

    repository = SourceRuntimeConfigRepository(
        session_factory=lambda: _session_scope(session_factory),
    )

    servers = repository.list_servers()
    profile_items = repository.list_profile_items(signal_profile.signal_profile_id)

    assert len(servers) == 1
    assert servers[0].asset_code == "WTG_01"
    assert servers[0].asset_name == "WTG 01"
    assert servers[0].ld_name == "WTG_01"
    assert servers[0].application_protocol == "OPC_UA"
    assert servers[0].signal_profile_id == signal_profile.signal_profile_id

    assert [item.do_name for item in profile_items] == ["TotW", "WS"]
    assert profile_items[0].relative_path == "MMXU1.TotW"
    assert profile_items[0].data_type == "FLOAT64"


def test_repository_can_limit_servers_to_first_group() -> None:
    """Return only the first server group when requested by the caller."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    session_factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)

    with _session_scope(session_factory) as session:
        asset_type = AssetType(type_code="WTG", type_name="Wind Turbine")
        session.add(asset_type)
        session.flush()

        signal_profile_1 = SignalProfile(
            profile_code="WTG_PROFILE_V1",
            profile_name="WTG Profile V1",
        )
        signal_profile_2 = SignalProfile(
            profile_code="WTG_PROFILE_V2",
            profile_name="WTG Profile V2",
        )
        session.add_all([signal_profile_1, signal_profile_2])
        session.flush()

        for index, (asset_code, profile_id, protocol) in enumerate(
            (
                ("WTG_01", signal_profile_1.signal_profile_id, "OPC_UA"),
                ("WTG_02", signal_profile_1.signal_profile_id, "OPC_UA"),
                ("WTG_03", signal_profile_2.signal_profile_id, "MODBUS"),
            ),
            start=1,
        ):
            asset = AssetInstance(
                asset_code=asset_code,
                asset_name=asset_code,
                asset_type_id=asset_type.asset_type_id,
            )
            session.add(asset)
            session.flush()

            ied = IED(
                asset_instance_id=asset.asset_instance_id,
                ied_name=f"IED_{asset_code}",
            )
            session.add(ied)
            session.flush()

            endpoint = CommunicationEndpoint(
                ied_id=ied.ied_id,
                access_point_name=f"AP_{index}",
                application_protocol=protocol,
                transport="TCP",
                host="127.0.0.1",
                port=4840 + index,
            )
            session.add(endpoint)
            session.flush()

            session.add(
                LDInstance(
                    endpoint_id=endpoint.endpoint_id,
                    asset_instance_id=asset.asset_instance_id,
                    signal_profile_id=profile_id,
                    ld_name=asset_code,
                )
            )

        session.commit()

    repository = SourceRuntimeConfigRepository(
        session_factory=lambda: _session_scope(session_factory),
    )

    servers = repository.list_servers(
        group_by=("signal_profile_id", "application_protocol"),
        first_group_only=True,
    )

    assert [server.asset_code for server in servers] == ["WTG_01", "WTG_02"]
