"""Unit tests for ingest sample-data loading."""

from __future__ import annotations

from pathlib import Path

import yaml
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from whale.ingest.framework.persistence.base import Base
from whale.ingest.framework.persistence.orm.source_runtime_config_orm import (
    SourceRuntimeConfigORM,
)
from whale.ingest.framework.persistence.sample_data_loader import (
    _load_connection_samples,
)


def test_load_connection_samples_uses_once_for_all_runtime_configs(
    tmp_path: Path,
) -> None:
    """Write ONCE runtime configs for every generated sample source."""
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)()
    config_path = tmp_path / "opcua-connections.yaml"
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

    try:
        _load_connection_samples(session, config_path)
        session.flush()

        acquisition_modes = list(
            session.scalars(
                select(SourceRuntimeConfigORM.acquisition_mode).order_by(
                    SourceRuntimeConfigORM.source_id
                )
            )
        )

        assert acquisition_modes == ["ONCE", "ONCE"]
    finally:
        session.close()
        engine.dispose()
