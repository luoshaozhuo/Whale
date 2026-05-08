"""Integration tests for the multiprocessing simulator fleet runtime."""

from __future__ import annotations

import asyncio
import socket
from typing import cast
import pytest

from tools.source_simulation.adapters.registry import build_source_reader
from tools.source_simulation.domain import (
    SimulatedPoint,
    SimulatedSource,
    SourceConnection,
    UpdateConfig,
)
from tools.source_simulation.fleet import SourceSimulatorFleet


def _get_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _build_source(
    name: str, port: int, *, namespace_uri: str = "urn:test:fleet"
) -> SimulatedSource:
    return SimulatedSource(
        connection=SourceConnection(
            name=name,
            ied_name=name,
            ld_name="LD0",
            host="127.0.0.1",
            port=port,
            transport="tcp",
            protocol="opcua",
            namespace_uri=namespace_uri,
        ),
        points=(
            SimulatedPoint(
                ln_name="MMXU1",
                do_name="TotW",
                unit="kW",
                data_type="FLOAT64",
                initial_value=1.0,
            ),
            SimulatedPoint(
                ln_name="GGIO1",
                do_name="TurSt",
                unit=None,
                data_type="BOOLEAN",
                initial_value=False,
            ),
        ),
    )


async def _list_nodes(source: SimulatedSource) -> tuple:
    async with build_source_reader(source.connection) as reader:
        return await reader.list_nodes()


async def _read_value(source: SimulatedSource, node_path: str) -> object:
    async with build_source_reader(source.connection) as reader:
        batch = await reader.read([node_path], fast_mode=False)
    return batch[0].value


async def _sample_values(
    source: SimulatedSource,
    node_path: str,
    *,
    sample_count: int,
    interval_seconds: float,
) -> list[object]:
    values: list[object] = []
    async with build_source_reader(source.connection) as reader:
        for _ in range(sample_count):
            batch = await reader.read([node_path], fast_mode=False)
            values.append(batch[0].value)
            await asyncio.sleep(interval_seconds)
    return values


async def _node_path_by_key(source: SimulatedSource, point_key: str) -> str:
    nodes = await _list_nodes(source)
    node_path_by_key = {f"{node.ln_name}.{node.do_name}": node.node_path for node in nodes}
    return cast(str, node_path_by_key[point_key])


@pytest.mark.integration
def test_fleet_context_starts_multiple_servers_and_reader_can_connect() -> None:
    sources = (
        _build_source("WTG_01", _get_free_port()),
        _build_source("WTG_02", _get_free_port()),
    )
    fleet = SourceSimulatorFleet.create(
        sources=sources,
        update_config=UpdateConfig(enabled=False, interval_seconds=0.2),
    )

    with fleet:
        assert len(fleet._processes) == len(sources)
        for source in sources:
            assert len(asyncio.run(_list_nodes(source))) == len(source.points)


@pytest.mark.integration
def test_fleet_disabled_updates_do_not_change_values() -> None:
    source = _build_source("WTG_01", _get_free_port())
    fleet = SourceSimulatorFleet.create(
        sources=[source],
        update_config=UpdateConfig(enabled=False, interval_seconds=0.2),
    )

    with fleet:
        node_path = asyncio.run(_node_path_by_key(source, "MMXU1.TotW"))
        values = asyncio.run(
            _sample_values(
                source,
                node_path,
                sample_count=4,
                interval_seconds=0.2,
            )
        )

    assert values == [1.0, 1.0, 1.0, 1.0]


@pytest.mark.integration
def test_fleet_enabled_updates_change_values_inside_child_process() -> None:
    source = _build_source("WTG_01", _get_free_port())
    fleet = SourceSimulatorFleet.create(
        sources=[source],
        update_config=UpdateConfig(enabled=True, interval_seconds=0.2, update_count=1),
    )

    with fleet:
        node_path = asyncio.run(_node_path_by_key(source, "MMXU1.TotW"))
        values = asyncio.run(
            _sample_values(
                source,
                node_path,
                sample_count=8,
                interval_seconds=0.2,
            )
        )

    assert len(set(values)) >= 2


@pytest.mark.integration
def test_fleet_stop_is_idempotent_and_cleans_up_processes() -> None:
    source = _build_source("WTG_01", _get_free_port())
    fleet = SourceSimulatorFleet.create(
        sources=[source],
        update_config=UpdateConfig(enabled=False, interval_seconds=0.2),
    )

    fleet.start()
    processes = tuple(fleet._processes)

    fleet.stop()
    fleet.stop()

    assert fleet._processes == []
    assert all(not process.is_alive() for process in processes)


@pytest.mark.integration
def test_fleet_context_exit_stops_all_child_processes() -> None:
    source = _build_source("WTG_01", _get_free_port())
    fleet = SourceSimulatorFleet.create(
        sources=[source],
        update_config=UpdateConfig(enabled=False, interval_seconds=0.2),
    )

    with fleet:
        processes = tuple(fleet._processes)
        assert processes

    assert fleet._processes == []
    assert all(not process.is_alive() for process in processes)


@pytest.mark.integration
def test_fleet_start_failure_raises_runtime_error_and_cleans_started_processes() -> None:
    good_source = _build_source("WTG_01", _get_free_port())
    bad_source = _build_source("WTG_02", _get_free_port(), namespace_uri="")
    fleet = SourceSimulatorFleet.create(
        sources=[good_source, bad_source],
        update_config=UpdateConfig(enabled=False, interval_seconds=0.2),
    )

    with pytest.raises(RuntimeError, match="Failed to start simulator fleet"):
        fleet.start()

    assert fleet._processes == []
    assert fleet._stop_events == []
    assert fleet._ready_events == []

    with pytest.raises(Exception):
        asyncio.run(_read_value(good_source, "ns=2;s=WTG_01.LD0.MMXU1.TotW"))
