"""Unit tests for ingest sample-data loading."""

from __future__ import annotations

from pathlib import Path

import yaml
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from whale.ingest.framework.persistence.base import Base
from whale.ingest.framework.persistence.orm.acquisition_task_orm import (
    AcquisitionTaskORM,
)
from whale.ingest.framework.persistence.sample_data_loader import load_sample_data


def test_load_sample_data_uses_once_for_all_acquisition_tasks(
    tmp_path: Path,
) -> None:
    """Write ONCE acquisition tasks for every generated sample device."""
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)()
    config_path = tmp_path / "opcua-connections.yaml"
    nodeset_path = tmp_path / "nodeset.xml"
    config_path.write_text(
        yaml.safe_dump(
            {
                "connections": [
                    {
                        "name": "WTG_01",
                        "endpoint": "opc.tcp://127.0.0.1:4840",
                        "security_policy": "None",
                        "security_mode": "None",
                        "update_interval_ms": 100,
                    },
                    {
                        "name": "WTG_02",
                        "endpoint": "opc.tcp://127.0.0.1:4841",
                        "security_policy": "None",
                        "security_mode": "None",
                        "update_interval_ms": 200,
                    },
                ]
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    nodeset_path.write_text(
        """
<UANodeSet xmlns="http://opcfoundation.org/UA/2011/03/UANodeSet.xsd">
  <NamespaceUris>
    <Uri>http://opcfoundation.org/UA/</Uri>
    <Uri>urn:windfarm:2wtg</Uri>
  </NamespaceUris>
</UANodeSet>
""".strip() + "\n",
        encoding="utf-8",
    )

    try:
        load_sample_data(session, config_path, nodeset_path)

        acquisition_modes = list(
            session.scalars(
                select(AcquisitionTaskORM.acquisition_mode).order_by(AcquisitionTaskORM.id)
            )
        )
        connection_hosts = list(
            session.scalars(select(AcquisitionTaskORM.host).order_by(AcquisitionTaskORM.id))
        )
        connection_ports = list(
            session.scalars(select(AcquisitionTaskORM.port).order_by(AcquisitionTaskORM.id))
        )
        protocols = list(
            session.scalars(select(AcquisitionTaskORM.protocol).order_by(AcquisitionTaskORM.id))
        )
        namespace_uris = [
            params.get("namespace_uri")
            for params in session.scalars(
                select(AcquisitionTaskORM.connection_params).order_by(AcquisitionTaskORM.id)
            )
        ]

        assert acquisition_modes == ["ONCE", "ONCE"]
        assert connection_hosts == ["127.0.0.1", "127.0.0.1"]
        assert connection_ports == [4840, 4841]
        assert protocols == ["opcua", "opcua"]
        assert namespace_uris == ["urn:windfarm:2wtg", "urn:windfarm:2wtg"]
    finally:
        session.close()
        engine.dispose()
