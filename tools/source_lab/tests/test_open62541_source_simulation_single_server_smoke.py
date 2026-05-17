"""Smoke test for open62541 OPC UA source simulator backend."""

from __future__ import annotations

import asyncio
import random
import socket
import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parents[3]
_SRC_ROOT = _PROJECT_ROOT / "src"
for _path in (str(_PROJECT_ROOT), str(_SRC_ROOT)):
    if _path not in sys.path:
        sys.path.insert(0, _path)

import pytest
from asyncua import Client  # type: ignore[import-untyped]
from asyncua import ua  # type: ignore[import-untyped]

from tools.source_lab.opcua.address_space import logical_path
from tools.source_lab.opcua.open62541_source_simulator import (
    Open62541SourceSimulator,
    resolve_runner_path,
)
from tools.source_lab.model import (
    SimulatedPoint,
    SimulatedSource,
    SourceConnection,
    UpdateConfig,
)
from tools.source_lab.fleet import SourceSimulatorFleet


def _expect_float(value: object) -> float:
    """Assert test value is float-compatible and return typed float."""
    assert isinstance(value, (int, float))
    return float(value)


def _expect_int(value: object) -> int:
    """Assert test value is int-compatible and return typed int."""
    assert isinstance(value, int)
    return value


def _expect_bool(value: object) -> bool:
    """Assert test value is bool and return typed bool."""
    assert isinstance(value, bool)
    return value


def _expect_str(value: object) -> str:
    """Assert test value is str and return typed str."""
    assert isinstance(value, str)
    return value


def _choose_available_port(
    *,
    host: str = "127.0.0.1",
    minimum_port: int = 40001,
    maximum_port: int = 59999,
) -> int:
    """Choose currently bindable TCP port."""
    rng = random.SystemRandom()
    tried: set[int] = set()

    while True:
        candidate = rng.randint(minimum_port, maximum_port)
        if candidate in tried:
            continue

        tried.add(candidate)

        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

            try:
                sock.bind((host, candidate))
            except OSError:
                if len(tried) >= maximum_port - minimum_port + 1:
                    raise RuntimeError("No available TCP ports found")
                continue

            return candidate


def _build_source() -> SimulatedSource:
    """Build minimal OPC UA source with 4 variables."""
    port = _choose_available_port()

    return SimulatedSource(
        connection=SourceConnection(
            name="open62541_smoke_source",
            ied_name="IED001",
            ld_name="LD0",
            host="127.0.0.1",
            port=port,
            transport="tcp",
            protocol="opcua",
            namespace_uri="urn:whale:open62541:smoke",
        ),
        points=(
            SimulatedPoint(
                ln_name="WPPD1",
                do_name="TotW",
                unit="kW",
                data_type="FLOAT64",
                initial_value=12.5,
            ),
            SimulatedPoint(
                ln_name="WPPD1",
                do_name="DevSt",
                unit=None,
                data_type="BOOLEAN",
                initial_value=True,
            ),
            SimulatedPoint(
                ln_name="WPPD1",
                do_name="OpCnt",
                unit=None,
                data_type="INT32",
                initial_value=7,
            ),
            SimulatedPoint(
                ln_name="WPPD1",
                do_name="StrVal",
                unit=None,
                data_type="STRING",
                initial_value="initial",
            ),
        ),
    )


async def _read_points(source: SimulatedSource) -> dict[str, object]:
    """Read all smoke-test points using asyncua client."""
    endpoint = f"opc.tcp://{source.connection.host}:{source.connection.port}"

    async with Client(url=endpoint) as client:
        ns_idx = await client.get_namespace_index(str(source.connection.namespace_uri))
        values: dict[str, object] = {}

        for point in source.points:
            node = client.get_node(
                f"ns={ns_idx};s={logical_path(source.connection, point)}"
            )
            values[point.key] = await node.read_value()

        return values


async def _read_data_values(source: SimulatedSource) -> dict[str, ua.DataValue]:
    """Read full DataValue objects requesting both source and server timestamps."""
    endpoint = f"opc.tcp://{source.connection.host}:{source.connection.port}"

    async with Client(url=endpoint) as client:
        ns_idx = await client.get_namespace_index(str(source.connection.namespace_uri))
        values: dict[str, ua.DataValue] = {}

        read_params = ua.ReadParameters()
        read_params.TimestampsToReturn = ua.TimestampsToReturn.Both
        for point in source.points:
            node = client.get_node(
                f"ns={ns_idx};s={logical_path(source.connection, point)}"
            )
            rv = ua.ReadValueId()
            rv.NodeId = node.nodeid
            rv.AttributeId = ua.AttributeIds.Value
            read_params.NodesToRead.append(rv)

        results = await client.uaclient.read(read_params)
        for point, dv in zip(source.points, results):
            values[point.key] = dv

        return values


def _assert_data_value_timestamps(
    data_values: dict[str, ua.DataValue],
    *,
    label: str,
) -> None:
    """Assert all DataValues have non-None Value, SourceTimestamp, ServerTimestamp."""
    for key, dv in data_values.items():
        assert dv.Value is not None, f"[{label}] {key}: Value is None"
        assert dv.SourceTimestamp is not None, (
            f"[{label}] {key}: SourceTimestamp is None"
        )
        assert dv.ServerTimestamp is not None, (
            f"[{label}] {key}: ServerTimestamp is None"
        )


def _require_runner() -> None:
    """Skip smoke tests when the open62541 runner has not been built."""
    runner_path = resolve_runner_path()
    if not runner_path.exists():
        pytest.skip(
            "open62541 runner executable does not exist. "
            "Build it with CMake before running this smoke test."
        )


@pytest.mark.load
def test_open62541_source_simulation_single_server_smoke(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Start one open62541 server and read several nodes with asyncua client."""
    _require_runner()

    monkeypatch.setenv("SOURCE_SIM_OPCUA_BACKEND", "open62541")
    monkeypatch.setenv("SOURCE_SIM_LOAD_SOURCE_UPDATE_ENABLED", "false")

    source = _build_source()

    fleet = SourceSimulatorFleet.create(
        sources=(source,),
        update_config=UpdateConfig(
            enabled=False,
            interval_seconds=1.0,
            update_count=len(source.points),
        ),
    )

    with fleet:
        values = asyncio.run(_read_points(source))
        data_values = asyncio.run(_read_data_values(source))

    assert len(values) == 4
    assert _expect_float(values["WPPD1.TotW"]) == 12.5
    assert _expect_bool(values["WPPD1.DevSt"]) is True
    assert _expect_int(values["WPPD1.OpCnt"]) == 7
    assert _expect_str(values["WPPD1.StrVal"]) == "initial"

    _assert_data_value_timestamps(data_values, label="initial")


@pytest.mark.load
def test_open62541_source_simulator_writes_smoke(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Write several value types through the open62541 runner and read them back."""
    _require_runner()

    monkeypatch.setenv("SOURCE_SIM_LOAD_SOURCE_UPDATE_ENABLED", "false")
    source = _build_source()

    with Open62541SourceSimulator(source) as simulator:
        initial_values = asyncio.run(_read_points(source))
        initial_data_values = asyncio.run(_read_data_values(source))

        assert _expect_float(initial_values["WPPD1.TotW"]) == 12.5
        assert _expect_int(initial_values["WPPD1.OpCnt"]) == 7
        assert _expect_bool(initial_values["WPPD1.DevSt"]) is True
        assert _expect_str(initial_values["WPPD1.StrVal"]) == "initial"

        _assert_data_value_timestamps(initial_data_values, label="pre-write")

        simulator.writes(
            {
                "WPPD1.TotW": 88.5,
                "WPPD1.OpCnt": 42,
                "WPPD1.DevSt": False,
                "WPPD1.StrVal": "updated",
            }
        )

        asyncio.run(asyncio.sleep(0.1))
        updated_values = asyncio.run(_read_points(source))
        post_write_data_values = asyncio.run(_read_data_values(source))

        assert _expect_float(updated_values["WPPD1.TotW"]) == 88.5
        assert _expect_int(updated_values["WPPD1.OpCnt"]) == 42
        assert _expect_bool(updated_values["WPPD1.DevSt"]) is False
        assert _expect_str(updated_values["WPPD1.StrVal"]) == "updated"

        _assert_data_value_timestamps(post_write_data_values, label="post-write")

        simulator.writes({"IED001.LD0.WPPD1.TotW": 99.5})

        asyncio.run(asyncio.sleep(0.1))
        logical_write_values = asyncio.run(_read_points(source))

        assert _expect_float(logical_write_values["WPPD1.TotW"]) == 99.5


@pytest.mark.load
def test_open62541_source_simulator_rejects_invalid_write_string(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Reject string writes containing control characters that break stdin commands."""
    _require_runner()

    monkeypatch.setenv("SOURCE_SIM_LOAD_SOURCE_UPDATE_ENABLED", "false")
    source = _build_source()

    with Open62541SourceSimulator(source) as simulator:
        with pytest.raises(ValueError, match="unsupported control character"):
            simulator.writes({"WPPD1.StrVal": "bad\tvalue"})


@pytest.mark.load
def test_open62541_source_simulator_internal_updates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify the open62541 runner can update values internally without Python writes."""
    _require_runner()

    monkeypatch.setenv("SOURCE_SIM_LOAD_SOURCE_UPDATE_ENABLED", "true")
    monkeypatch.setenv("SOURCE_SIM_LOAD_SOURCE_UPDATE_HZ", "10")

    source = _build_source()

    with Open62541SourceSimulator(source):
        initial_values = asyncio.run(_read_points(source))
        initial_data_values = asyncio.run(_read_data_values(source))

        asyncio.run(asyncio.sleep(0.3))

        updated_values = asyncio.run(_read_points(source))
        updated_data_values = asyncio.run(_read_data_values(source))

    assert any(updated_values[key] != initial_values[key] for key in initial_values)
    assert any(
        updated_data_values[key].SourceTimestamp != initial_data_values[key].SourceTimestamp
        or updated_data_values[key].ServerTimestamp != initial_data_values[key].ServerTimestamp
        for key in updated_data_values
    )

    _assert_data_value_timestamps(initial_data_values, label="internal-pre")
    _assert_data_value_timestamps(updated_data_values, label="internal-post")


@pytest.mark.load
def test_open62541_fleet_internal_updates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify fleet-driven open62541 startup works with runner-side internal updates enabled."""
    _require_runner()

    monkeypatch.setenv("SOURCE_SIM_OPCUA_BACKEND", "open62541")
    monkeypatch.setenv("SOURCE_SIM_LOAD_SOURCE_UPDATE_ENABLED", "true")
    monkeypatch.setenv("SOURCE_SIM_LOAD_SOURCE_UPDATE_HZ", "10")

    source = _build_source()
    fleet = SourceSimulatorFleet.create(
        sources=(source,),
        update_config=UpdateConfig(
            enabled=True,
            interval_seconds=0.1,
            update_count=4,
        ),
    )

    with fleet:
        initial_values = asyncio.run(_read_points(source))
        initial_data_values = asyncio.run(_read_data_values(source))
        asyncio.run(asyncio.sleep(0.3))
        updated_values = asyncio.run(_read_points(source))
        updated_data_values = asyncio.run(_read_data_values(source))

    assert any(updated_values[key] != initial_values[key] for key in initial_values)
    _assert_data_value_timestamps(initial_data_values, label="fleet-internal-pre")
    _assert_data_value_timestamps(updated_data_values, label="fleet-internal-post")
