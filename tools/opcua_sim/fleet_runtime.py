"""Helpers for starting multiple simulator servers from YAML config or whale DB."""

from __future__ import annotations

import tempfile
from pathlib import Path

import yaml
from sqlalchemy import select

from tools.opcua_sim.generate_nodeset import generate_nodeset_from_measurement_points
from tools.opcua_sim.models import OpcUaServerConfig
from tools.opcua_sim.server_runtime import (
    DEFAULT_NAMESPACE_URI,
    OpcUaServerRuntime,
    load_server_config,
)


class OpcUaFleetRuntime:
    """Manage a group of simulator servers defined in one connection config."""

    def __init__(self, runtimes: list[OpcUaServerRuntime],
                 _temp_dir: tempfile.TemporaryDirectory | None = None) -> None:
        self._runtimes = runtimes
        self._temp_dir = _temp_dir

    @classmethod
    def from_connection_config(
        cls, nodeset_path: str | Path, config_path: str | Path,
        namespace_uri: str = DEFAULT_NAMESPACE_URI,
    ) -> "OpcUaFleetRuntime":
        raw_config = yaml.safe_load(Path(config_path).read_text(encoding="utf-8"))
        connections = raw_config.get("connections", []) if isinstance(raw_config, dict) else []
        runtimes = [
            OpcUaServerRuntime(
                nodeset_path=nodeset_path,
                config=load_server_config(config_path, str(item["name"])),
                namespace_uri=namespace_uri,
            )
            for item in connections
        ]
        return cls(runtimes)

    @classmethod
    def from_database(
        cls, namespace_uri: str = DEFAULT_NAMESPACE_URI,
    ) -> "OpcUaFleetRuntime":
        from whale.shared.persistence.session import session_scope

        with session_scope() as session:
            from whale.shared.persistence.orm import (
                AcquisitionTask, AssetInstance, AssetType,
                CommunicationEndpoint, LDInstance,
                SignalProfileItem, ScadaDataType,
            )

            wt_type = session.scalars(
                select(AssetType).where(AssetType.type_code == "WTG")
            ).first()
            if wt_type is None:
                raise RuntimeError("AssetType 'WTG' not found")

            tasks = (
                session.scalars(
                    select(AcquisitionTask)
                    .join(LDInstance)
                    .join(AssetInstance)
                    .where(AssetInstance.asset_type_id == wt_type.asset_type_id)
                    .order_by(AcquisitionTask.task_id)
                ).all()
            )
            if not tasks:
                raise RuntimeError("No turbine acquisition tasks found")

            # Build measurement points from the first task's LDInstance
            first_ld = session.get(LDInstance, tasks[0].ld_instance_id)
            items = session.scalars(
                select(SignalProfileItem)
                .where(SignalProfileItem.signal_profile_id == first_ld.signal_profile_id)
                .order_by(SignalProfileItem.profile_item_id)
            ).all()

            mps = []
            for item in items:
                dt = session.get(ScadaDataType, item.data_type_id) if item.data_type_id else None
                mps.append({
                    "do_name": item.do_name,
                    "data_type": dt.type_name if dt else "FLOAT64",
                    "unit": item.default_unit,
                    "display_name": item.display_name or item.do_name,
                })

            field_means = _load_field_means()
            turbine_names = [
                session.get(AssetInstance,
                    session.get(LDInstance, t.ld_instance_id).asset_instance_id
                ).asset_code
                for t in tasks
            ]

            nodeset_xml, variable_means = generate_nodeset_from_measurement_points(
                measurement_points=mps, turbine_names=turbine_names,
                field_means=field_means,
            )

            tmp_dir = tempfile.TemporaryDirectory(prefix="opcua_sim_")
            nodeset_path = Path(tmp_dir.name) / "nodeset.xml"
            nodeset_path.write_text(nodeset_xml, encoding="utf-8")

            runtimes = []
            for task in tasks:
                ld = session.get(LDInstance, task.ld_instance_id)
                asset = session.get(AssetInstance, ld.asset_instance_id)
                task_ep = session.get(CommunicationEndpoint, ld.endpoint_id)
                if task_ep and task_ep.host and task_ep.port:
                    ep_url = f"opc.tcp://{task_ep.host}:{task_ep.port}"
                else:
                    ep_url = ""
                runtimes.append(OpcUaServerRuntime(
                    nodeset_path=str(nodeset_path),
                    config=OpcUaServerConfig(
                        name=asset.asset_code,
                        endpoint=ep_url,
                        security_policy=str(task_ep.security_policy or "None") if task_ep else "None",
                        security_mode=str(task_ep.security_mode or "None") if task_ep else "None",
                        update_interval_seconds=100 / 1000.0,
                    ),
                    namespace_uri=namespace_uri,
                    variable_means=variable_means,
                ))

            return cls(runtimes, _temp_dir=tmp_dir)

    def start(self) -> "OpcUaFleetRuntime":
        for runtime in self._runtimes:
            runtime.start()
        return self

    def stop(self) -> None:
        for runtime in reversed(self._runtimes):
            runtime.stop()

    @property
    def endpoints(self) -> dict[str, str]:
        return {runtime.name: runtime.endpoint for runtime in self._runtimes}

    def __enter__(self) -> "OpcUaFleetRuntime":
        return self.start()

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        self.stop()


def _load_field_means() -> dict[str, float]:
    try:
        from whale.shared.persistence.template.gbt_30966_fields import ALL_LOGICAL_NODES
        result: dict[str, float] = {}
        for node in ALL_LOGICAL_NODES:
            for f in node.fields:
                result[f.key] = f.mean
        return result
    except Exception:
        return {}
