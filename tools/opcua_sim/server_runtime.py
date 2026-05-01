"""Single OPC UA server runtime built from a NodeSet fixture."""

from __future__ import annotations

import math
import random
import threading
import time
from pathlib import Path

import yaml
from asyncua import ua  # type: ignore[import-untyped]
from asyncua.sync import Server  # type: ignore[import-untyped]

from tools.opcua_sim.models import OpcUaServerConfig

DEFAULT_NAMESPACE_URI = "urn:windfarm:2wtg"
DEFAULT_UPDATE_INTERVAL_SECONDS = 5.0
DEFAULT_STDDEV_RATIO = 0.02
DEFAULT_SINE_PERIOD_SECONDS = 5.0
DEFAULT_SINE_AMPLITUDE_RATIO = 0.15
DEFAULT_PHASE_STEP_DEGREES = 90.0
DEFAULT_VARIABLE_VALUES: dict[str, float] = {"TotW": 1200.0, "Spd": 12.5, "WS": 6.8}

_OCP_TYPE_ID_MAP: dict[int, str] = {11: "Double", 6: "Int32", 1: "Boolean", 12: "String"}


class OpcUaServerRuntimeError(ValueError):
    """Raised when simulator bootstrap input is invalid."""


def build_simulated_variable_value(
    variable_name: str,
    mean: float,
    elapsed_seconds: float,
    random_component: float,
    *,
    period_seconds: float = DEFAULT_SINE_PERIOD_SECONDS,
    amplitude_ratio: float = DEFAULT_SINE_AMPLITUDE_RATIO,
    phase_step_degrees: float = DEFAULT_PHASE_STEP_DEGREES,
) -> float:
    """Build one simulated value from the variable mean, noise and phase-shifted sine wave."""
    phase_radians = math.radians((hash(variable_name) % 360) * phase_step_degrees)
    sine_component = (
        abs(mean)
        * amplitude_ratio
        * math.sin(((2.0 * math.pi) / period_seconds) * elapsed_seconds + phase_radians)
    )
    return max(0.0, mean + random_component + sine_component)


def load_server_config(path: str | Path, connection_name: str) -> OpcUaServerConfig:
    """Load one OPC UA endpoint definition from the YAML connection config."""
    raw_config = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    connections = raw_config.get("connections", []) if isinstance(raw_config, dict) else []
    default_update_interval_ms = DEFAULT_UPDATE_INTERVAL_SECONDS * 1000.0

    for item in connections:
        if item.get("name") == connection_name:
            return OpcUaServerConfig(
                name=str(item["name"]),
                endpoint=str(item["endpoint"]),
                security_policy=str(item.get("security_policy", "None")),
                security_mode=str(item.get("security_mode", "None")),
                update_interval_seconds=float(
                    item.get("update_interval_ms", default_update_interval_ms)
                )
                / 1000.0,
            )
    raise OpcUaServerRuntimeError(
        f"Connection `{connection_name}` was not found in config: {path}"
    )


class OpcUaServerRuntime:
    """Start and stop one simulator server from a NodeSet file and endpoint config."""

    def __init__(
        self,
        nodeset_path: str | Path,
        config: OpcUaServerConfig,
        namespace_uri: str = DEFAULT_NAMESPACE_URI,
        variable_means: dict[str, float] | None = None,
    ) -> None:
        self._nodeset_path = Path(nodeset_path)
        self._config = config
        self._namespace_uri = namespace_uri
        self._variable_means = variable_means or dict(DEFAULT_VARIABLE_VALUES)
        self._server: Server | None = None
        self._stop_updates = threading.Event()
        self._update_thread: threading.Thread | None = None
        self._random = random.Random(self._config.name)

    @property
    def endpoint(self) -> str:
        return self._config.endpoint

    @property
    def name(self) -> str:
        return self._config.name

    def start(self) -> "OpcUaServerRuntime":
        if self._server is not None:
            return self
        server = Server()
        server.set_endpoint(self._config.endpoint)
        # Set security policy if configured (skip for "None" to avoid cert errors)
        sp = self._config.security_policy
        sm = self._config.security_mode
        if sp and sm and sp != "None" and sm != "None":
            try:
                server.set_security_policy([
                    ua.SecurityPolicyType[sp],
                    ua.MessageSecurityMode[sm],
                ])
            except (KeyError, AttributeError):
                pass
        server.import_xml(path=str(self._nodeset_path))
        self._materialize_type_variables(server)
        server.start()
        self._server = server
        self._start_value_updates(server)
        return self

    def stop(self) -> None:
        if self._server is None:
            return
        self._stop_value_updates()
        self._server.stop()
        self._server = None

    def __enter__(self) -> "OpcUaServerRuntime":
        return self.start()

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        self.stop()

    # ── internals ──────────────────────────────────────────────────

    def _materialize_type_variables(self, server: Server) -> None:
        """Instantiate variables for the configured turbine, remove other instances."""
        namespace_index = server.get_namespace_index(self._namespace_uri)
        objects = server.nodes.objects
        windfarm = objects.get_child(f"{namespace_index}:WindFarm")
        type_node = server.get_node(ua.NodeId("WindTurbineType", namespace_index))
        type_variables = [(child.read_browse_name().Name,
                           self._resolve_variant_type(child))
                          for child in type_node.get_children()]

        for turbine in windfarm.get_children():
            turbine_name = turbine.read_browse_name().Name
            if turbine_name != self._config.name:
                turbine.delete(recursive=True)
                continue
            existing_children = {child.read_browse_name().Name
                                 for child in turbine.get_children()}
            for variable_name, variant_type in type_variables:
                if variable_name in existing_children:
                    continue
                default = 0
                if variant_type == ua.VariantType.Boolean:
                    default = False
                elif variant_type == ua.VariantType.String:
                    default = ""
                elif variant_type == ua.VariantType.Int32:
                    default = 0
                turbine.add_variable(
                    ua.NodeId(f"{turbine_name}.{variable_name}", namespace_index),
                    ua.QualifiedName(variable_name, namespace_index),
                    default,
                    varianttype=variant_type,
                )

    @staticmethod
    def _resolve_variant_type(node) -> int:
        try:
            dt_attr = node.read_data_type()
            dt_id = dt_attr.Identifier if hasattr(dt_attr, "Identifier") else 11
            if isinstance(dt_id, int):
                return {11: ua.VariantType.Double, 6: ua.VariantType.Int32,
                        1: ua.VariantType.Boolean, 12: ua.VariantType.String}.get(
                        dt_id, ua.VariantType.Double)
        except Exception:
            pass
        return ua.VariantType.Double

    def _start_value_updates(self, server: Server) -> None:
        if self._config.update_interval_seconds <= 0:
            return
        variable_specs = self._build_variable_specs(server)
        if not variable_specs:
            return
        self._stop_updates.clear()
        self._update_thread = threading.Thread(
            target=self._run_value_updates,
            args=(server, variable_specs),
            daemon=True,
            name=f"opcua-sim-{self._config.name}",
        )
        self._update_thread.start()

    def _stop_value_updates(self) -> None:
        self._stop_updates.set()
        if self._update_thread is not None:
            self._update_thread.join(timeout=max(self._config.update_interval_seconds, 1.0))
            self._update_thread = None

    def _build_variable_specs(
        self, server: Server
    ) -> dict[str, tuple[str, float, str]]:
        """Build specs for ALL variables under the turbine (not filtered)."""
        namespace_index = server.get_namespace_index(self._namespace_uri)
        turbine = server.nodes.objects.get_child(
            [f"{namespace_index}:WindFarm", f"{namespace_index}:{self._config.name}"]
        )
        specs: dict[str, tuple[str, float, str]] = {}

        for child in turbine.get_children():
            var_name = child.read_browse_name().Name
            dt_name = self._read_data_type_name(child)
            mean = self._variable_means.get(var_name, 0.0)
            if var_name not in self._variable_means:
                try:
                    current = child.read_value()
                    if isinstance(current, (int, float)) and current != 0:
                        mean = float(current)
                except Exception:
                    pass
            specs[child.nodeid.to_string()] = (var_name, mean, dt_name)
        return specs

    @staticmethod
    def _read_data_type_name(node) -> str:
        try:
            dt_attr = node.read_data_type()
            dt_id = dt_attr.Identifier if hasattr(dt_attr, "Identifier") else 11
            if isinstance(dt_id, int):
                return _OCP_TYPE_ID_MAP.get(dt_id, "Double")
        except Exception:
            pass
        return "Double"

    def _run_value_updates(
        self,
        server: Server,
        variable_specs: dict[str, tuple[str, float, str]],
    ) -> None:
        started_at = time.monotonic()
        while not self._stop_updates.wait(self._config.update_interval_seconds):
            elapsed_seconds = time.monotonic() - started_at
            for node_id, (variable_name, mean, dt_name) in variable_specs.items():
                try:
                    next_value = build_simulated_variable_value(
                        variable_name, mean, elapsed_seconds,
                        self._random.gauss(0.0, abs(mean) * DEFAULT_STDDEV_RATIO),
                    )
                    if dt_name == "Int32":
                        server.get_node(node_id).write_value(
                            ua.Variant(int(next_value), ua.VariantType.Int32))
                    elif dt_name == "Boolean":
                        server.get_node(node_id).write_value(
                            ua.Variant(next_value >= 0.5, ua.VariantType.Boolean))
                    elif dt_name == "String":
                        server.get_node(node_id).write_value(
                            ua.Variant(str(next_value), ua.VariantType.String))
                    else:
                        server.get_node(node_id).write_value(
                            ua.Variant(next_value, ua.VariantType.Double))
                except Exception:
                    pass
