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
DEFAULT_VARIABLE_VALUES = {
    "TotW": 1200.0,
    "Spd": 12.5,
    "WS": 6.8,
}


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
    phase_index = tuple(DEFAULT_VARIABLE_VALUES).index(variable_name)
    phase_radians = math.radians(phase_index * phase_step_degrees)
    sine_component = (
        abs(mean)
        * amplitude_ratio
        * math.sin(((2.0 * math.pi) / period_seconds) * elapsed_seconds + phase_radians)
    )
    return max(0.0, mean + random_component + sine_component)


def load_server_config(path: str | Path, connection_name: str) -> OpcUaServerConfig:
    """Load one OPC UA endpoint definition from the YAML connection config.

    Args:
        path: YAML config path.
        connection_name: Connection entry name to load.

    Returns:
        Parsed server config for the requested connection.

    Raises:
        OpcUaServerRuntimeError: If the config file cannot be parsed or the named
            connection does not exist.
    """
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

    raise OpcUaServerRuntimeError(f"Connection `{connection_name}` was not found in config: {path}")


class OpcUaServerRuntime:
    """Start and stop one simulator server from a NodeSet file and YAML endpoint."""

    def __init__(
        self,
        nodeset_path: str | Path,
        config: OpcUaServerConfig,
        namespace_uri: str = DEFAULT_NAMESPACE_URI,
    ) -> None:
        """Store immutable bootstrap inputs for the simulator runtime.

        Args:
            nodeset_path: Path to the NodeSet XML used to populate the server.
            config: Endpoint configuration resolved from the YAML file.
            namespace_uri: Custom namespace URI expected inside the NodeSet.
        """
        self._nodeset_path = Path(nodeset_path)
        self._config = config
        self._namespace_uri = namespace_uri
        self._server: Server | None = None
        self._stop_updates = threading.Event()
        self._update_thread: threading.Thread | None = None
        self._random = random.Random(self._config.name)

    @property
    def endpoint(self) -> str:
        """Return the configured OPC UA endpoint."""
        return self._config.endpoint

    @property
    def name(self) -> str:
        """Return the logical server name."""
        return self._config.name

    def start(self) -> "OpcUaServerRuntime":
        """Start the OPC UA server and materialize runtime variables.

        Returns:
            The running runtime instance.
        """
        if self._server is not None:
            return self

        server = Server()
        server.set_endpoint(self._config.endpoint)
        server.import_xml(path=str(self._nodeset_path))
        self._materialize_type_variables(server)
        server.start()
        self._server = server
        self._start_value_updates(server)
        return self

    def stop(self) -> None:
        """Stop the OPC UA server and release the listening socket."""
        if self._server is None:
            return
        self._stop_value_updates()
        self._server.stop()
        self._server = None

    def __enter__(self) -> "OpcUaServerRuntime":
        """Start the runtime when entering a context manager."""
        return self.start()

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        """Stop the runtime when leaving a context manager."""
        self.stop()

    def _materialize_type_variables(self, server: Server) -> None:
        """Instantiate variables for the configured turbine and remove other instances."""
        namespace_index = server.get_namespace_index(self._namespace_uri)
        objects = server.nodes.objects
        windfarm = objects.get_child(f"{namespace_index}:WindFarm")
        type_node = server.get_node(ua.NodeId("WindTurbineType", namespace_index))
        type_variables = [child.read_browse_name().Name for child in type_node.get_children()]

        for turbine in windfarm.get_children():
            turbine_name = turbine.read_browse_name().Name
            if turbine_name != self._config.name:
                turbine.delete(recursive=True)
                continue
            existing_children = {child.read_browse_name().Name for child in turbine.get_children()}
            for variable_name in type_variables:
                if variable_name in existing_children:
                    continue
                turbine.add_variable(
                    ua.NodeId(f"{turbine_name}.{variable_name}", namespace_index),
                    ua.QualifiedName(variable_name, namespace_index),
                    DEFAULT_VARIABLE_VALUES.get(variable_name, 0.0),
                    varianttype=ua.VariantType.Double,
                )

    def _start_value_updates(self, server: Server) -> None:
        """Start the background loop that periodically refreshes turbine values."""
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
        """Stop the background value refresh loop if it is running."""
        self._stop_updates.set()
        if self._update_thread is not None:
            self._update_thread.join(timeout=max(self._config.update_interval_seconds, 1.0))
            self._update_thread = None

    def _build_variable_specs(self, server: Server) -> dict[str, tuple[str, float]]:
        """Build the per-variable name and mean map from the default simulation values."""
        namespace_index = server.get_namespace_index(self._namespace_uri)
        turbine = server.nodes.objects.get_child(
            [f"{namespace_index}:WindFarm", f"{namespace_index}:{self._config.name}"]
        )
        variable_specs: dict[str, tuple[str, float]] = {}

        for child in turbine.get_children():
            variable_name = child.read_browse_name().Name
            if variable_name not in DEFAULT_VARIABLE_VALUES:
                continue
            variable_specs[child.nodeid.to_string()] = (
                variable_name,
                DEFAULT_VARIABLE_VALUES[variable_name],
            )

        return variable_specs

    def _run_value_updates(
        self,
        server: Server,
        variable_specs: dict[str, tuple[str, float]],
    ) -> None:
        """Periodically refresh each turbine variable around its configured mean."""
        started_at = time.monotonic()
        while not self._stop_updates.wait(self._config.update_interval_seconds):
            elapsed_seconds = time.monotonic() - started_at
            for node_id, (variable_name, mean) in variable_specs.items():
                random_component = self._random.gauss(0.0, abs(mean) * DEFAULT_STDDEV_RATIO)
                next_value = build_simulated_variable_value(
                    variable_name,
                    mean,
                    elapsed_seconds,
                    random_component,
                )
                server.get_node(node_id).write_value(ua.Variant(next_value, ua.VariantType.Double))
