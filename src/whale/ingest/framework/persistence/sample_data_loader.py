"""Sample-data loading helpers for ingest persistence."""

from __future__ import annotations

from pathlib import Path
from xml.etree import ElementTree

import yaml
from sqlalchemy.orm import Session

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

UA_NODESET_NS = {"ua": "http://opcfoundation.org/UA/2011/03/UANodeSet.xsd"}
DEFAULT_SAMPLE_ITEM_KEYS = ("TotW", "Spd", "WS")
DEFAULT_SAMPLE_SUBSTATION = "DEMO_SUBSTATION"
DEFAULT_SAMPLE_MODEL_ID = "goldwind_gw121_opcua"
DEFAULT_SAMPLE_MODEL_VERSION = "v1"


def load_sample_data(
    session: Session,
    connection_config_path: Path,
    nodeset_path: Path,
) -> None:
    """Load sample acquisition assets and tasks into the database."""
    namespace_uri = _resolve_primary_namespace_uri(nodeset_path)
    _load_substation_sample(session)
    _load_acquisition_model_samples(session, namespace_uri)
    session.flush()
    _load_device_and_task_samples(session, connection_config_path)
    session.commit()


def _load_substation_sample(session: Session) -> None:
    """Load one default sample substation."""
    session.add(
        SubstationORM(
            name=DEFAULT_SAMPLE_SUBSTATION,
            enabled=True,
        )
    )


def _load_acquisition_model_samples(session: Session, namespace_uri: str | None) -> None:
    """Load one shared sample acquisition model."""
    model = AcquisitionModelORM(
        model_id=DEFAULT_SAMPLE_MODEL_ID,
        model_version=DEFAULT_SAMPLE_MODEL_VERSION,
        protocol="opcua",
        model_params=({"namespace_uri": namespace_uri} if namespace_uri is not None else {}),
    )
    session.add(model)
    session.flush()

    for sort_order, item_key in enumerate(DEFAULT_SAMPLE_ITEM_KEYS):
        session.add(
            AcquisitionVariableORM(
                model_id=int(model.id),
                variable_key=item_key,
                locator=f"s={{device_code}}.{item_key}",
                locator_type="node_path",
                display_name=item_key,
                variable_params={},
                sort_order=sort_order,
                enabled=True,
            )
        )


def _load_device_and_task_samples(session: Session, connection_config_path: Path) -> None:
    """Load sample devices and acquisition tasks from one connection YAML."""
    raw_config = yaml.safe_load(connection_config_path.read_text(encoding="utf-8")) or {}
    connections = raw_config.get("connections", [])
    substation_id = int(
        session.query(SubstationORM.id)
        .filter(SubstationORM.name == DEFAULT_SAMPLE_SUBSTATION)
        .one()[0]
    )

    for index, item in enumerate(connections, start=1):
        device_code = str(item["name"])
        update_interval_ms = int(item["update_interval_ms"])
        line_number = f"L{index}"

        device = DeviceORM(
            substation_id=substation_id,
            device_code=device_code,
            device_model="GENERIC_WTG",
            line_number=line_number,
            enabled=True,
        )
        session.add(device)
        session.flush()

        session.add(
            AcquisitionTaskORM(
                device_id=int(device.id),
                model_id=DEFAULT_SAMPLE_MODEL_ID,
                model_version=DEFAULT_SAMPLE_MODEL_VERSION,
                acquisition_mode="ONCE",
                interval_ms=update_interval_ms,
                endpoint=str(item["endpoint"]),
                connection_params={
                    "security_policy": str(item["security_policy"]),
                    "security_mode": str(item["security_mode"]),
                },
                enabled=True,
            )
        )


def _resolve_primary_namespace_uri(nodeset_path: Path) -> str | None:
    """Return the first non-default namespace URI from one NodeSet file."""
    root = ElementTree.parse(nodeset_path).getroot()
    uris = [
        (element.text or "").strip()
        for element in root.findall("./ua:NamespaceUris/ua:Uri", UA_NODESET_NS)
        if (element.text or "").strip()
    ]
    return uris[1] if len(uris) > 1 else (uris[0] if uris else None)
