"""Unit tests for polling acquisition role."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import cast

from whale.ingest.ports.source.source_acquisition_port import (
    SourceAcquisitionPort,
    SourceSubscriptionHandle,
    SubscriptionStateHandler,
)
from whale.ingest.ports.state.source_state_cache_port import SourceStateCachePort
from whale.ingest.usecases.dtos.acquired_node_state import AcquiredNodeState
from whale.ingest.usecases.dtos.source_acquisition_request import (
    AcquisitionExecutionOptions,
    AcquisitionItemData,
    SourceAcquisitionRequest,
)
from whale.ingest.usecases.dtos.source_acquisition_start_result import (
    SourceAcquisitionStartResult,
)
from whale.ingest.usecases.dtos.source_connection_data import SourceConnectionData
from whale.ingest.usecases.roles.polling_acquisition_role import (
    PollingAcquisitionSession,
    PollingAcquisitionRole,
)


class FakeSourceAcquisitionPort:
    def __init__(
        self,
        *,
        states_by_ld_name: dict[str, list[AcquiredNodeState]] | None = None,
        read_delay_seconds: float = 0.0,
        error: Exception | None = None,
    ) -> None:
        self._states_by_ld_name = states_by_ld_name or {}
        self._read_delay_seconds = read_delay_seconds
        self._error = error
        self.read_calls: list[
            tuple[object, SourceConnectionData, list[AcquisitionItemData], float]
        ] = []
        self.active_read_count = 0
        self.max_active_read_count = 0

    async def read(
        self,
        execution: object,
        connection: SourceConnectionData,
        items: list[AcquisitionItemData],
    ) -> list[AcquiredNodeState]:
        loop = asyncio.get_running_loop()
        self.read_calls.append((execution, connection, list(items), loop.time()))

        self.active_read_count += 1
        self.max_active_read_count = max(
            self.max_active_read_count,
            self.active_read_count,
        )

        try:
            if self._read_delay_seconds > 0:
                await asyncio.sleep(self._read_delay_seconds)

            if self._error is not None:
                raise self._error

            return list(self._states_by_ld_name.get(connection.ld_name, []))
        finally:
            self.active_read_count -= 1

    async def start_subscription(
        self,
        execution: AcquisitionExecutionOptions,
        connection: SourceConnectionData,
        items: list[AcquisitionItemData],
        *,
        state_received: SubscriptionStateHandler,
    ) -> SourceSubscriptionHandle:
        del execution, connection, items, state_received
        raise NotImplementedError


class FakeStateCachePort:
    def __init__(self) -> None:
        self.calls: list[tuple[str, list[AcquiredNodeState]]] = []

    def update(
        self,
        *,
        ld_name: str,
        states: list[AcquiredNodeState],
    ) -> int:
        self.calls.append((ld_name, list(states)))
        return len(states)


def _build_connection(index: int) -> SourceConnectionData:
    return SourceConnectionData(
        host=f"127.0.0.{index}",
        port=4840 + index,
        ied_name=f"IED_{index:02d}",
        ld_name=f"LD_{index:02d}",
        namespace_uri="urn:test",
    )


def _build_request(
    *,
    interval_ms: int = 20,
    max_iteration: int | None = 3,
    acquisition_mode: str = "POLLING",
    connections: list[SourceConnectionData] | None = None,
    polling_max_concurrent_connections: int = 4,
    polling_connection_start_interval_ms: int = 0,
) -> SourceAcquisitionRequest:
    return SourceAcquisitionRequest(
        request_id="request-1",
        task_id=101,
        execution=AcquisitionExecutionOptions(
            protocol="opcua",
            transport="tcp",
            acquisition_mode=acquisition_mode,
            interval_ms=interval_ms,
            max_iteration=max_iteration,
            request_timeout_ms=500,
            freshness_timeout_ms=30000,
            alive_timeout_ms=60000,
            polling_max_concurrent_connections=polling_max_concurrent_connections,
            polling_connection_start_interval_ms=polling_connection_start_interval_ms,
        ),
        connections=connections if connections is not None else [_build_connection(1)],
        items=[AcquisitionItemData("TotW", 1, "TotW")],
    )


def _build_states(source_id: str, value: str) -> list[AcquiredNodeState]:
    return [
        AcquiredNodeState(
            source_id=source_id,
            node_key="TotW",
            value=value,
            observed_at=datetime.now(tz=UTC),
        )
    ]


def test_start_returns_source_acquisition_start_result() -> None:
    async def _run() -> None:
        port = FakeSourceAcquisitionPort(
            states_by_ld_name={"LD_01": _build_states("LD_01", "1")}
        )
        role = PollingAcquisitionRole(
            acquisition_port=cast(SourceAcquisitionPort, port),
            state_cache_port=cast(SourceStateCachePort, FakeStateCachePort()),
        )

        request = _build_request(max_iteration=1)
        start_result = role.start(request)

        assert isinstance(start_result, SourceAcquisitionStartResult)
        assert start_result.request_id == request.request_id
        assert start_result.task_id == request.task_id
        assert start_result.mode == "POLLING"
        assert len(start_result.sessions) == 1
        assert isinstance(start_result.sessions[0], PollingAcquisitionSession)

        await cast(PollingAcquisitionSession, start_result.sessions[0]).task

    asyncio.run(_run())


def test_read_once_is_expressed_by_max_iteration_one() -> None:
    async def _run() -> None:
        port = FakeSourceAcquisitionPort(
            states_by_ld_name={"LD_01": _build_states("LD_01", "1")}
        )
        cache = FakeStateCachePort()
        role = PollingAcquisitionRole(
            acquisition_port=cast(SourceAcquisitionPort, port),
            state_cache_port=cast(SourceStateCachePort, cache),
        )

        start_result = role.start(_build_request(max_iteration=1))
        await cast(PollingAcquisitionSession, start_result.sessions[0]).task

        assert len(port.read_calls) == 1
        assert len(cache.calls) == 1
        assert cache.calls[0][0] == "LD_01"
        assert cache.calls[0][1][0].value == "1"

    asyncio.run(_run())


def test_finite_polling_runs_expected_iterations() -> None:
    async def _run() -> None:
        port = FakeSourceAcquisitionPort(
            states_by_ld_name={"LD_01": _build_states("LD_01", "1")}
        )
        role = PollingAcquisitionRole(
            acquisition_port=cast(SourceAcquisitionPort, port),
            state_cache_port=cast(SourceStateCachePort, FakeStateCachePort()),
        )

        start_result = role.start(_build_request(max_iteration=3, interval_ms=10))
        await cast(PollingAcquisitionSession, start_result.sessions[0]).task

        assert len(port.read_calls) == 3

    asyncio.run(_run())


def test_infinite_polling_can_be_stopped() -> None:
    async def _run() -> None:
        port = FakeSourceAcquisitionPort(
            states_by_ld_name={"LD_01": _build_states("LD_01", "1")}
        )
        role = PollingAcquisitionRole(
            acquisition_port=cast(SourceAcquisitionPort, port),
            state_cache_port=cast(SourceStateCachePort, FakeStateCachePort()),
        )

        start_result = role.start(_build_request(max_iteration=None, interval_ms=10))
        session = cast(PollingAcquisitionSession, start_result.sessions[0])

        await asyncio.sleep(0.05)
        await session.close()

        assert len(port.read_calls) >= 1
        assert session.closed is True

    asyncio.run(_run())


def test_cache_update_is_called_with_ld_name_and_states() -> None:
    async def _run() -> None:
        cache = FakeStateCachePort()
        role = PollingAcquisitionRole(
            acquisition_port=cast(
                SourceAcquisitionPort,
                FakeSourceAcquisitionPort(
                    states_by_ld_name={"LD_01": _build_states("LD_01", "42.0")}
                ),
            ),
            state_cache_port=cast(SourceStateCachePort, cache),
        )

        start_result = role.start(_build_request(max_iteration=1))
        await cast(PollingAcquisitionSession, start_result.sessions[0]).task

        assert cache.calls == [("LD_01", cache.calls[0][1])]
        assert cache.calls[0][1][0].node_key == "TotW"
        assert cache.calls[0][1][0].value == "42.0"

    asyncio.run(_run())


def test_empty_states_do_not_update_cache() -> None:
    async def _run() -> None:
        cache = FakeStateCachePort()
        role = PollingAcquisitionRole(
            acquisition_port=cast(SourceAcquisitionPort, FakeSourceAcquisitionPort()),
            state_cache_port=cast(SourceStateCachePort, cache),
        )

        start_result = role.start(_build_request(max_iteration=1))
        await cast(PollingAcquisitionSession, start_result.sessions[0]).task

        assert cache.calls == []

    asyncio.run(_run())


def test_reads_multiple_connections_once_per_cycle() -> None:
    async def _run() -> None:
        connections = [_build_connection(1), _build_connection(2), _build_connection(3)]
        port = FakeSourceAcquisitionPort(
            states_by_ld_name={
                "LD_01": _build_states("LD_01", "1"),
                "LD_02": _build_states("LD_02", "2"),
                "LD_03": _build_states("LD_03", "3"),
            }
        )
        cache = FakeStateCachePort()
        role = PollingAcquisitionRole(
            acquisition_port=cast(SourceAcquisitionPort, port),
            state_cache_port=cast(SourceStateCachePort, cache),
        )

        start_result = role.start(
            _build_request(
                max_iteration=1,
                connections=connections,
            )
        )
        await cast(PollingAcquisitionSession, start_result.sessions[0]).task

        assert [call[1].ld_name for call in port.read_calls] == [
            "LD_01",
            "LD_02",
            "LD_03",
        ]
        assert [call[0] for call in cache.calls] == ["LD_01", "LD_02", "LD_03"]

    asyncio.run(_run())


def test_max_concurrent_connections_limits_parallel_reads() -> None:
    async def _run() -> None:
        connections = [_build_connection(1), _build_connection(2), _build_connection(3)]
        port = FakeSourceAcquisitionPort(read_delay_seconds=0.02)
        role = PollingAcquisitionRole(
            acquisition_port=cast(SourceAcquisitionPort, port),
            state_cache_port=cast(SourceStateCachePort, FakeStateCachePort()),
        )

        start_result = role.start(
            _build_request(
                max_iteration=1,
                connections=connections,
                polling_max_concurrent_connections=1,
            )
        )
        await cast(PollingAcquisitionSession, start_result.sessions[0]).task

        assert port.max_active_read_count == 1
        assert len(port.read_calls) == 3

    asyncio.run(_run())


def test_connection_start_interval_staggers_read_start_time() -> None:
    async def _run() -> None:
        connections = [_build_connection(1), _build_connection(2)]
        port = FakeSourceAcquisitionPort()
        role = PollingAcquisitionRole(
            acquisition_port=cast(SourceAcquisitionPort, port),
            state_cache_port=cast(SourceStateCachePort, FakeStateCachePort()),
        )

        start_result = role.start(
            _build_request(
                max_iteration=1,
                connections=connections,
                polling_connection_start_interval_ms=20,
            )
        )
        await cast(PollingAcquisitionSession, start_result.sessions[0]).task

        assert len(port.read_calls) == 2
        first_started_at = port.read_calls[0][3]
        second_started_at = port.read_calls[1][3]
        assert second_started_at - first_started_at >= 0.015

    asyncio.run(_run())


def test_polling_exception_bubbles_from_background_task() -> None:
    async def _run() -> None:
        role = PollingAcquisitionRole(
            acquisition_port=cast(
                SourceAcquisitionPort,
                FakeSourceAcquisitionPort(error=ConnectionError("boom")),
            ),
            state_cache_port=cast(SourceStateCachePort, FakeStateCachePort()),
        )

        start_result = role.start(_build_request(max_iteration=1))
        session = cast(PollingAcquisitionSession, start_result.sessions[0])

        try:
            await session.task
        except ConnectionError as exc:
            assert str(exc) == "boom"
        else:
            raise AssertionError("Expected ConnectionError")

    asyncio.run(_run())