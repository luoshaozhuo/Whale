"""Sample-data loading helpers for ingest persistence."""

from __future__ import annotations

from pathlib import Path
from urllib.parse import urlsplit
from xml.etree import ElementTree

import yaml
from sqlalchemy.orm import Session

from whale.shared.persistence.orm import (
    AcquisitionTask,
    AssetInstance,
    AssetType,
    DA,
    DO,
    IED,
    LD,
    LN,
    OrganizationLevel,
)

UA_NODESET_NS = {"ua": "http://opcfoundation.org/UA/2011/03/UANodeSet.xsd"}
DEFAULT_SAMPLE_ITEM_KEYS = ("TotW", "Spd", "WS")
DEFAULT_SAMPLE_PLANT = "DEMO_PLANT"
DEFAULT_SAMPLE_MODEL_ID = "goldwind_gw121_opcua"
DEFAULT_SAMPLE_MODEL_VERSION = "v1"
DEFAULT_STANDARD_MODEL_ID = "gbt_30966_opcua"


def load_sample_data(
    session: Session,
    connection_config_path: Path,
    nodeset_path: Path,
) -> None:
    """Load sample acquisition assets and tasks into the database."""
    namespace_uri = _resolve_primary_namespace_uri(nodeset_path)
    org_level, asset_type = _load_org_and_type_sample(session)
    session.flush()
    _load_asset_and_task_samples(session, connection_config_path, namespace_uri, org_level, asset_type)
    session.commit()


def _load_org_and_type_sample(session: Session) -> tuple[OrganizationLevel, AssetType]:
    """Load default org level and wind-turbine asset type."""
    org_level = OrganizationLevel(org_level_name=DEFAULT_SAMPLE_PLANT)
    session.add(org_level)

    asset_type = AssetType(
        asset_type_name="风力发电机",
        category="电气设备",
        description="示例风机类型",
    )
    session.add(asset_type)
    return org_level, asset_type


def _load_asset_and_task_samples(
    session: Session,
    connection_config_path: Path,
    namespace_uri: str | None,
    org_level: OrganizationLevel,
    asset_type: AssetType,
) -> None:
    """Load sample asset instances, IED hierarchy, and acquisition tasks."""
    raw_config = yaml.safe_load(connection_config_path.read_text(encoding="utf-8")) or {}
    connections = raw_config.get("connections", [])

    for index, item in enumerate(connections, start=1):
        device_code = str(item["name"])
        update_interval_ms = int(item["update_interval_ms"])
        line_number = f"L{index}"
        host, port = _parse_endpoint(str(item["endpoint"]))
        endpoint = str(item["endpoint"])

        # ---- 资产实例 ----
        asset = AssetInstance(
            asset_code=device_code,
            asset_type_id=asset_type.asset_type_id,
            org_level_id=org_level.org_level_id,
            location=line_number,
            operational_status="运行",
        )
        session.add(asset)
        session.flush()

        # ---- IED → LD → LN → DO → DA 层级 ----
        ied = IED(
            ied_name=f"IED_{device_code}",
            protocol_type="opcua",
            protocol_address=endpoint,
        )
        session.add(ied)
        session.flush()

        ld = LD(ld_name="MEAS", ied_id=ied.ied_id)
        session.add(ld)
        session.flush()

        ln = LN(ln_name="WTUR", ln_type="WTUR", ld_id=ld.ld_id)
        session.add(ln)
        session.flush()

        for item_key in DEFAULT_SAMPLE_ITEM_KEYS:
            do = DO(do_name=item_key, ln_id=ln.ln_id, cdc="MV", fc="MX")
            session.add(do)
            session.flush()

            session.add(
                DA(
                    do_id=do.do_id,
                    da_name="mag.f",
                    data_type="FLOAT32",
                    unit=_unit_for_key(item_key),
                    locator=f"s={{device_code}}.{item_key}",
                    locator_type="node_path",
                    display_name=item_key,
                    variable_params={},
                    enabled=True,
                )
            )

        # ---- 采集任务 ----
        session.add(
            AcquisitionTask(
                task_name=f"task_{device_code}",
                asset_instance_id=asset.asset_instance_id,
                ied_id=ied.ied_id,
                protocol_type="opcua",
                acquisition_mode="ONCE",
                sampling_interval_ms=update_interval_ms,
                endpoint=endpoint,
                namespace_uri=namespace_uri,
                params={
                    "host": host,
                    "port": port,
                    "security_policy": str(item.get("security_policy", "")),
                    "security_mode": str(item.get("security_mode", "")),
                },
                enabled=True,
            )
        )


def _unit_for_key(key: str) -> str | None:
    return {"TotW": "kW", "Spd": "rpm", "WS": "m/s"}.get(key)


def _resolve_primary_namespace_uri(nodeset_path: Path) -> str | None:
    root = ElementTree.parse(nodeset_path).getroot()
    uris = [
        (element.text or "").strip()
        for element in root.findall("./ua:NamespaceUris/ua:Uri", UA_NODESET_NS)
        if (element.text or "").strip()
    ]
    return uris[1] if len(uris) > 1 else (uris[0] if uris else None)


def _parse_endpoint(endpoint: str) -> tuple[str | None, int | None]:
    parsed = urlsplit(endpoint)
    return parsed.hostname, parsed.port


def load_standard_sample_data(
    session: Session,
    connection_config_path: Path,
    *,
    plant_name: str = DEFAULT_SAMPLE_PLANT,
    model_id: str = DEFAULT_STANDARD_MODEL_ID,
    model_version: str = DEFAULT_SAMPLE_MODEL_VERSION,
) -> None:
    """Load sample data using the full GB/T 30966.2 field set (~500 fields)."""
    from tools.opcua_sim.templates.gbt_30966_fields import ALL_LOGICAL_NODES

    namespace_uri = _resolve_primary_namespace_uri(
        connection_config_path.parent / "OPCUANodeSet.xml"
    )
    org_level, asset_type = _load_org_and_type_sample_with_names(
        session, plant_name=plant_name
    )
    session.flush()
    _load_standard_ied_hierarchy(session, namespace_uri, model_id=model_id)
    session.flush()
    _load_asset_and_task_samples(session, connection_config_path, namespace_uri, org_level, asset_type)


def _load_org_and_type_sample_with_names(
    session: Session, *, plant_name: str
) -> tuple[OrganizationLevel, AssetType]:
    org_level = OrganizationLevel(org_level_name=plant_name)
    session.add(org_level)

    asset_type = AssetType(
        asset_type_name="风力发电机",
        category="电气设备",
        description="GB/T 30966.2 标准风机采集",
    )
    session.add(asset_type)
    return org_level, asset_type


def _load_standard_ied_hierarchy(
    session: Session,
    namespace_uri: str | None,
    *,
    model_id: str = DEFAULT_STANDARD_MODEL_ID,
) -> None:
    """Load GB/T 30966.2 fields as IED → LD → LN → DO → DA hierarchy."""
    from tools.opcua_sim.templates.gbt_30966_fields import ALL_LOGICAL_NODES

    ied = IED(
        ied_name=f"IED_{model_id}",
        protocol_type="opcua",
    )
    session.add(ied)
    session.flush()

    ld = LD(ld_name="CTL", ied_id=ied.ied_id)
    session.add(ld)
    session.flush()

    for node in ALL_LOGICAL_NODES:
        ln = LN(ln_name=node.name, ln_type=node.name, ld_id=ld.ld_id)
        session.add(ln)
        session.flush()

        for field in node.fields:
            do = DO(do_name=field.key, ln_id=ln.ln_id, cdc="MV", fc="MX")
            session.add(do)
            session.flush()

            session.add(
                DA(
                    do_id=do.do_id,
                    da_name="mag.f",
                    data_type="FLOAT32",
                    unit=field.unit,
                    locator=f"s={{device_code}}.{field.key}",
                    locator_type="node_path",
                    display_name=f"{field.desc} ({field.unit})",
                    variable_params={},
                    enabled=True,
                )
            )
