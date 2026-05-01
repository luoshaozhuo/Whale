"""Helpers for starting multiple simulator servers from YAML config or whale DB."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
from typing import Any

import yaml

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
        self._temp_dir = _temp_dir  # hold reference so it's not GC'd

    @classmethod
    def from_connection_config(
        cls,
        nodeset_path: str | Path,
        config_path: str | Path,
        namespace_uri: str = DEFAULT_NAMESPACE_URI,
    ) -> "OpcUaFleetRuntime":
        """Build one runtime per connection entry found in the YAML config."""
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
        cls,
        namespace_uri: str = DEFAULT_NAMESPACE_URI,
    ) -> "OpcUaFleetRuntime":
        """Build runtimes from whale shared-persistence DB (acq_task + v_measurement_point).

        Queries the shared persistence database for wind-turbine acquisition tasks,
        builds a NodeSet XML from the measurement point definitions, and creates one
        OPC UA server per turbine.
        """
        from whale.shared.persistence.session import session_scope

        with session_scope() as session:
            # ── Find the wind turbine asset type ──────────────────────
            from whale.shared.persistence.orm.asset import AssetType
            wt_type = session.query(AssetType).filter(
                AssetType.asset_type_name == "风力发电机"
            ).first()
            if wt_type is None:
                raise RuntimeError("AssetType '风力发电机' not found in database")

            # ── Query turbine acquisition tasks ───────────────────────
            from whale.shared.persistence.orm.acquisition import AcquisitionTask
            tasks = (
                session.query(AcquisitionTask)
                .filter(AcquisitionTask.asset_type_id == wt_type.asset_type_id)
                .order_by(AcquisitionTask.task_id)
                .all()
            )
            if not tasks:
                raise RuntimeError("No wind turbine acquisition tasks found in database")

            # ── Query measurement points from the first task's IED ────
            ied_id = tasks[0].ied_id
            mps = _query_measurement_points(session, ied_id)

            # ── Build field_means from gbt_30966_fields ────────────────
            field_means = _load_field_means()

            # ── Generate NodeSet XML with all DOs ─────────────────────
            turbine_names = [t.asset_instance.asset_code
                             if hasattr(t, 'asset_instance') and t.asset_instance
                             else f"WTG-{i+1:03d}"
                             for i, t in enumerate(tasks)]

            nodeset_xml, variable_means = generate_nodeset_from_measurement_points(
                measurement_points=mps,
                turbine_names=turbine_names,
                field_means=field_means,
            )

            # Write nodeset to a temp file
            tmp_dir = tempfile.TemporaryDirectory(prefix="opcua_sim_")
            nodeset_path = Path(tmp_dir.name) / "nodeset.xml"
            nodeset_path.write_text(nodeset_xml, encoding="utf-8")

            # ── Build runtimes ─────────────────────────────────────────
            runtimes = []
            for task in tasks:
                asset_code = task.asset_instance.asset_code if task.asset_instance else f"WTG-{task.task_id}"
                params = task.params or {}
                if isinstance(params, str):
                    params = json.loads(params)
                config = OpcUaServerConfig(
                    name=asset_code,
                    endpoint=task.endpoint,
                    security_policy=str(params.get("security_policy", "Basic256Sha256")),
                    security_mode=str(params.get("security_mode", "SignAndEncrypt")),
                    update_interval_seconds=task.sampling_interval_ms / 1000.0,
                )
                runtimes.append(OpcUaServerRuntime(
                    nodeset_path=str(nodeset_path),
                    config=config,
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

    def endpoints(self) -> dict[str, str]:
        return {runtime.name: runtime.endpoint for runtime in self._runtimes}

    def __enter__(self) -> "OpcUaFleetRuntime":
        return self.start()

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        self.stop()


def _query_measurement_points(session: Any, ied_id: int) -> list[dict[str, Any]]:
    """Query v_measurement_point for all DOs belonging to the given IED."""
    from sqlalchemy import text
    rows = session.execute(
        text(
            "SELECT do_id, do_name, cdc, fc, data_type, unit, "
            "constraint_expr, display_name, ln_id, ln_name, "
            "ln_description, ld_id, ld_name, ied_id, ied_name, protocol_type "
            "FROM v_measurement_point WHERE ied_id = :ied_id ORDER BY do_id"
        ),
        {"ied_id": ied_id},
    ).mappings().fetchall()
    return [dict(r) for r in rows]


def _load_field_means() -> dict[str, float]:
    """Load {do_name: mean_value} from gbt_30966_fields."""
    try:
        from whale.shared.persistence.template.gbt_30966_fields import ALL_LOGICAL_NODES
        result: dict[str, float] = {}
        for node in ALL_LOGICAL_NODES:
            for f in node.fields:
                result[f.key] = f.mean
        return result
    except Exception:
        return {}
