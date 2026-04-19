"""Integration tests for simulated OPC UA server runtimes."""

from __future__ import annotations

import subprocess
import threading
import time
from pathlib import Path

import pytest
import yaml
from asyncua import ua  # type: ignore[import-untyped]
from asyncua.sync import Client  # type: ignore[import-untyped]

from tools.opcua_sim.fleet_runtime import OpcUaFleetRuntime
from tools.opcua_sim.server_runtime import OpcUaServerRuntime

CLI_BROWSE_NODE = "ns=2;s=WindFarm"
CLI_STARTUP_TIMEOUT_SECONDS = 10.0
INTERVAL_TOLERANCE_SECONDS = 0.08


def _run_uals(endpoint: str) -> subprocess.CompletedProcess[str]:
    """Browse the wind farm node through the asyncua CLI.

    Args:
        endpoint: OPC UA endpoint to browse.

    Returns:
        Completed subprocess result for the browse command.
    """
    return subprocess.run(
        ["uals", "-u", endpoint, "-n", CLI_BROWSE_NODE, "-d", "2"],
        capture_output=True,
        text=True,
        check=False,
    )


def _assert_windfarm_browse_result(endpoint: str) -> None:
    """Assert that the target endpoint exposes the expected wind farm hierarchy.

    Args:
        endpoint: OPC UA endpoint to browse.
    """
    result = _run_uals(endpoint)
    if result.returncode != 0:
        raise AssertionError(
            f"`uals` failed for {endpoint} with code {result.returncode}: {result.stderr}"
        )

    assert "WindFarm" in result.stdout
    assert "WTG_01" in result.stdout
    assert "WTG_02" in result.stdout


def _wait_for_browsable_endpoint(
    endpoint: str,
    timeout_seconds: float = CLI_STARTUP_TIMEOUT_SECONDS,
) -> None:
    """Poll `uals` until the target endpoint becomes reachable.

    Args:
        endpoint: OPC UA endpoint to browse.
        timeout_seconds: Maximum time to wait for startup.

    Raises:
        AssertionError: If the endpoint never becomes reachable in time.
    """
    deadline = time.monotonic() + timeout_seconds
    last_result: subprocess.CompletedProcess[str] | None = None

    while time.monotonic() < deadline:
        last_result = _run_uals(endpoint)
        if last_result.returncode == 0:
            return
        time.sleep(0.2)

    stderr = last_result.stderr if last_result is not None else "no CLI output"
    raise AssertionError(f"Server at {endpoint} did not become browsable in time: {stderr}")


class _DataChangeCollector:
    """Collect data change timestamps from an OPC UA subscription."""

    def __init__(self) -> None:
        """Initialize the collector state."""
        self._timestamps: list[float] = []
        self._condition = threading.Condition()

    def datachange_notification(self, node: object, val: object, data: object) -> None:
        """Record the time of each incoming data change notification."""
        del node, val, data
        with self._condition:
            self._timestamps.append(time.monotonic())
            self._condition.notify_all()

    def wait_for_events(self, minimum_events: int, timeout_seconds: float) -> list[float]:
        """Wait until the requested number of timestamps has been collected."""
        deadline = time.monotonic() + timeout_seconds
        with self._condition:
            while len(self._timestamps) < minimum_events:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    break
                self._condition.wait(timeout=remaining)
            return list(self._timestamps)


def _mean_interval(timestamps: list[float]) -> float:
    """Compute the mean interval between consecutive timestamps."""
    intervals = [
        current - previous for previous, current in zip(timestamps, timestamps[1:], strict=False)
    ]
    return sum(intervals) / len(intervals)


@pytest.mark.integration
def test_uaserver_cli_imports_nodeset_template_and_exposes_windfarm(
    sample_nodeset_path: str,
) -> None:
    """Start the asyncua CLI server from the template NodeSet and browse it with uals."""
    endpoint = "opc.tcp://127.0.0.1:4840"
    process = subprocess.Popen(
        ["uaserver", "-x", sample_nodeset_path, "-u", endpoint],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        text=True,
    )

    try:
        _wait_for_browsable_endpoint(endpoint)
        _assert_windfarm_browse_result(endpoint)
    finally:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)


@pytest.mark.integration
def test_single_opcua_server_uses_yaml_endpoint_and_exposes_default_values(
    opcua_server_runtime: OpcUaServerRuntime,
) -> None:
    """Start one server from YAML config and read the materialized node defaults."""
    with Client(opcua_server_runtime.endpoint) as client:
        namespace_index = client.get_namespace_index("urn:windfarm:2wtg")
        windfarm = client.get_node(ua.ObjectIds.ObjectsFolder).get_child(
            f"{namespace_index}:WindFarm"
        )
        wtg_01 = windfarm.get_child(f"{namespace_index}:WTG_01")

        assert {child.read_browse_name().Name for child in windfarm.get_children()} == {"WTG_01"}
        assert {child.read_browse_name().Name for child in wtg_01.get_children()} == {
            "TotW",
            "Spd",
            "WS",
        }

        totw = client.get_node(f"ns={namespace_index};s=WTG_01.TotW")
        spd = client.get_node(f"ns={namespace_index};s=WTG_01.Spd")

        assert totw.read_value() == 1200.0
        assert spd.read_value() == 12.5


@pytest.mark.integration
def test_fleet_updates_each_turbine_with_its_configured_interval(
    opcua_sim_fleet: OpcUaFleetRuntime,
    sample_opcua_connections_path: str,
) -> None:
    """Subscribe to both servers and verify their update intervals match the YAML config."""
    config = yaml.safe_load(Path(sample_opcua_connections_path).read_text(encoding="utf-8"))
    assert isinstance(config, dict)
    connections = config.get("connections", [])
    assert isinstance(connections, list)

    interval_by_name = {
        str(item["name"]): float(item["update_interval_ms"]) / 1000.0 for item in connections
    }
    endpoints = opcua_sim_fleet.endpoints()

    for turbine_name in ("WTG_01", "WTG_02"):
        collector = _DataChangeCollector()
        with Client(endpoints[turbine_name]) as client:
            namespace_index = client.get_namespace_index("urn:windfarm:2wtg")
            variable = client.get_node(f"ns={namespace_index};s={turbine_name}.TotW")
            subscription = client.create_subscription(50, collector)
            handle = subscription.subscribe_data_change(variable)
            try:
                timestamps = collector.wait_for_events(minimum_events=4, timeout_seconds=5.0)
            finally:
                subscription.unsubscribe(handle)
                subscription.delete()

        assert len(timestamps) >= 4
        observed_interval = _mean_interval(timestamps)
        expected_interval = interval_by_name[turbine_name]
        assert abs(observed_interval - expected_interval) < INTERVAL_TOLERANCE_SECONDS


@pytest.mark.integration
def test_opcua_sim_fleet_starts_distinct_servers_from_yaml(
    opcua_sim_fleet: OpcUaFleetRuntime,
) -> None:
    """Start both configured servers and verify the fleet exposes distinct endpoints."""
    endpoints = opcua_sim_fleet.endpoints()

    assert set(endpoints) == {"WTG_01", "WTG_02"}
    assert len(set(endpoints.values())) == 2

    with Client(endpoints["WTG_01"]) as client_1:
        namespace_index = client_1.get_namespace_index("urn:windfarm:2wtg")
        windfarm = client_1.get_node(ua.ObjectIds.ObjectsFolder).get_child(
            f"{namespace_index}:WindFarm"
        )
        assert {child.read_browse_name().Name for child in windfarm.get_children()} == {"WTG_01"}

    with Client(endpoints["WTG_02"]) as client_2:
        namespace_index = client_2.get_namespace_index("urn:windfarm:2wtg")
        windfarm = client_2.get_node(ua.ObjectIds.ObjectsFolder).get_child(
            f"{namespace_index}:WindFarm"
        )
        assert {child.read_browse_name().Name for child in windfarm.get_children()} == {"WTG_02"}
