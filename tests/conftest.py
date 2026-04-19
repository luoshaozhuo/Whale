"""Shared pytest fixtures."""

from __future__ import annotations

import json
import socket
import sys
from pathlib import Path
from typing import Generator, cast

import pytest
import yaml

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SRC_ROOT = PROJECT_ROOT / "src"
OPCUA_SIM_TEMPLATE_DIR = PROJECT_ROOT / "tools" / "opcua_sim" / "templates"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from tools.opcua_sim.fleet_runtime import OpcUaFleetRuntime  # noqa: E402
from tools.opcua_sim.server_runtime import OpcUaServerRuntime, load_server_config  # noqa: E402
from whale.scenario1.models import PointMeta  # noqa: E402
from whale.scenario1.scl_registry import build_registry_maps, parse_scl_registry  # noqa: E402


@pytest.fixture()
def scenario1_fixture_dir() -> Path:
    """Return the directory that stores shared scenario1 fixtures.

    Returns:
        Fixture directory used by scenario1 tests.
    """
    return Path(__file__).parent / "fixtures" / "scenario1"


@pytest.fixture()
def sample_scl_path(scenario1_fixture_dir: Path) -> Path:
    """Return the sample SCL registry path for scenario1 tests.

    Args:
        scenario1_fixture_dir: Base fixture directory for scenario1.

    Returns:
        Path to the sample SCL file.
    """
    return scenario1_fixture_dir / "sample_scl.xml"


@pytest.fixture()
def sample_power_curve_path(scenario1_fixture_dir: Path) -> Path:
    """Return the sample power-curve CSV path for scenario1 tests.

    Args:
        scenario1_fixture_dir: Base fixture directory for scenario1.

    Returns:
        Path to the sample power-curve CSV file.
    """
    return scenario1_fixture_dir / "sample_power_curve.csv"


@pytest.fixture()
def sample_nodeset_path(scenario1_fixture_dir: Path) -> str:
    """Return the standard OPC UA NodeSet path for simulator tests.

    Args:
        scenario1_fixture_dir: Base fixture directory for scenario1.

    Returns:
        String path to the NodeSet fixture.
    """
    _ = scenario1_fixture_dir
    return str(OPCUA_SIM_TEMPLATE_DIR / "OPCUANodeSet.xml")


@pytest.fixture()
def sample_opcua_connections_path(scenario1_fixture_dir: Path) -> str:
    """Return the sample OPC UA connection config path for simulator tests.

    Args:
        scenario1_fixture_dir: Base fixture directory for scenario1.

    Returns:
        String path to the connection YAML fixture.
    """
    _ = scenario1_fixture_dir
    return str(OPCUA_SIM_TEMPLATE_DIR / "OPCUA_client_connections.yaml")


@pytest.fixture()
def sample_raw_payloads(scenario1_fixture_dir: Path) -> list[dict[str, object]]:
    """Load sample raw OPC UA payloads for scenario1 tests.

    Args:
        scenario1_fixture_dir: Base fixture directory for scenario1.

    Returns:
        Parsed mock raw batches loaded from the fixture JSON file.
    """
    return cast(
        list[dict[str, object]],
        json.loads((scenario1_fixture_dir / "sample_raw_batches.json").read_text(encoding="utf-8")),
    )


@pytest.fixture()
def scenario1_registry(sample_scl_path: Path) -> list[PointMeta]:
    """Load and parse the sample scenario1 registry.

    Args:
        sample_scl_path: Fixture path for the minimal SCL file.

    Returns:
        Parsed point metadata used by scenario1 tests.
    """
    return parse_scl_registry(sample_scl_path)


@pytest.fixture()
def scenario1_registry_maps(
    scenario1_registry: list[PointMeta],
) -> tuple[dict[str, PointMeta], dict[str, PointMeta]]:
    """Build scenario1 registry lookup maps for tests.

    Args:
        scenario1_registry: Parsed point metadata fixture.

    Returns:
        Lookup tables keyed by OPC UA node id and internal point code.
    """
    return build_registry_maps(scenario1_registry)


@pytest.fixture()
def free_ports() -> tuple[int, int]:
    """Return two currently free ports for simulator integration tests.

    Returns:
        Two free ports discovered from the OS.
    """
    ports: list[int] = []
    sockets: list[socket.socket] = []
    try:
        for _ in range(2):
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.bind(("127.0.0.1", 0))
            sockets.append(sock)
            ports.append(int(sock.getsockname()[1]))
    finally:
        for sock in sockets:
            sock.close()
    if len(ports) != 2:
        raise RuntimeError("Could not allocate two free ports for OPC UA simulator tests.")
    return ports[0], ports[1]


@pytest.fixture()
def local_opcua_connections_path(
    tmp_path: Path,
    sample_opcua_connections_path: str,
    free_ports: tuple[int, int],
) -> str:
    """Write a localhost-only connection YAML for integration tests.

    Args:
        tmp_path: Temporary directory for test-local fixture output.
        sample_opcua_connections_path: Source fixture config path.
        free_ports: Two free localhost ports allocated for the current test.

    Returns:
        Path to the rewritten localhost connection YAML.
    """
    config = cast(
        dict[str, object],
        yaml.safe_load(Path(sample_opcua_connections_path).read_text(encoding="utf-8")),
    )
    connections = cast(list[dict[str, object]], config["connections"])
    connections[0]["endpoint"] = f"opc.tcp://127.0.0.1:{free_ports[0]}"
    connections[1]["endpoint"] = f"opc.tcp://127.0.0.1:{free_ports[1]}"
    path = tmp_path / "OPCUA_client_connections.local.yaml"
    path.write_text(yaml.safe_dump(config, sort_keys=False), encoding="utf-8")
    return str(path)


@pytest.fixture()
def opcua_server_runtime(
    sample_nodeset_path: str,
    local_opcua_connections_path: str,
) -> Generator[OpcUaServerRuntime, None, None]:
    """Start a single simulator server for integration tests.

    Args:
        sample_nodeset_path: NodeSet XML fixture path.
        local_opcua_connections_path: Localhost-only connection YAML path.

    Yields:
        Running single-server runtime using the first connection entry.
    """
    runtime = OpcUaServerRuntime(
        nodeset_path=sample_nodeset_path,
        config=load_server_config(local_opcua_connections_path, "WTG_01"),
    )
    with runtime:
        yield runtime


@pytest.fixture()
def opcua_sim_fleet(
    sample_nodeset_path: str,
    local_opcua_connections_path: str,
) -> Generator[OpcUaFleetRuntime, None, None]:
    """Start all simulator servers described by the localhost test YAML.

    Args:
        sample_nodeset_path: NodeSet XML fixture path.
        local_opcua_connections_path: Localhost-only connection YAML path.

    Yields:
        Running fleet runtime for both wind turbine servers.
    """
    fleet = OpcUaFleetRuntime.from_connection_config(
        nodeset_path=sample_nodeset_path,
        config_path=local_opcua_connections_path,
    )
    with fleet:
        yield fleet
