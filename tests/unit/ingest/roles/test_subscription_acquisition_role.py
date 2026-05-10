"""Unit tests for subscription acquisition role."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import cast

from whale.ingest.ports.source.source_acquisition_port import (
    SourceAcquisitionPort,
    SourceSubscriptionHandle,
    SubscriptionStateHandler,
)
from whale.ingest.ports.state.source_state_cache_port import (
    ModeAwareSourceStateCachePort,
    SourceStateCachePort,
)
from whale.ingest.usecases.dtos.acquired_node_state import AcquiredNodeState
from whale.ingest.usecases.dtos.acquisition_execution_options import (
    AcquisitionExecutionOptions,
)
from whale.ingest.usecases.dtos.acquisition_item_data import AcquisitionItemData
from whale.ingest.usecases.dtos.source_acquisition_request import (
    SourceAcquisitionRequest,
)
from whale.ingest.usecases.dtos.source_connection_data import SourceConnectionData
from whale.ingest.usecases.roles.runtime_diagnostics_role import (
    RuntimeDiagnosticsRole,
)
from whale.ingest.usecases.roles.subscription_acquisition_role import (
    SubscriptionAcquisitionRole,
    SubscriptionAcquisitionStartResult,
    SubscriptionAcquisitionSession,
)


class FakeHandle(SourceSubscriptionHandle):
    def __init__(self) -> None:
        self.close_calls = 0

    async def close(self) -> None:
        self.close_calls += 1


class FakeSourceAcquisitionPort:
    def __init__(self) -> None:
        self.start_calls: list[
            tuple[
                object,
                SourceConnectionData,
                list[AcquisitionItemData],
                SubscriptionStateHandler,
            ]
        ] = []
        self.handles: list[FakeHandle] = []

    async def read(self, *args: object, **kwargs: object) -> list[AcquiredNodeState]:
        del args, kwargs
        raise NotImplementedError

    async def start_subscription(
        self,
        execution: object,
        connection: SourceConnectionData,
        items: list[AcquisitionItemData],
        *,
        state_received: SubscriptionStateHandler,
    ) -> SourceSubscriptionHandle:
        handle = FakeHandle()
        self.start_calls.append((execution, connection, list(items), state_received))
        self.handles.append(handle)
        return handle


class FakeStateCachePort:
    def __init__(self) -> None:
        self.calls: list[tuple[str, list[AcquiredNodeState]]] = []

    def store_many(
        self,
        model_id: str,
        acquired_states: list[AcquiredNodeState],
    ) -> int:
        self.calls.append((model_id, list(acquired_states)))
        return len(acquired_states)


class FakeModeAwareStateCachePort(ModeAwareSourceStateCachePort):
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, list[AcquiredNodeState]]] = []

    def store_many(
        self,
        model_id: str,
        acquired_states: list[AcquiredNodeState],
    ) -> int:
        self.calls.append(("plain", model_id, list(acquired_states)))
        return len(acquired_states)

    def store_many_for_mode(
        self,
        acquisition_mode: str,
        model_id: str,
        acquired_states: list[AcquiredNodeState],
    ) -> int:
        self.calls.append((acquisition_mode, model_id, list(acquired_states)))
        return len(acquired_states)


class FakeDiagnosticsRole:
    def __init__(self) -> None:
        self.keepalive_calls: list[tuple[int, int, str]] = []

    def record_keepalive(
        self,
        task_id: int,
        ld_instance_id: int,
        acquisition_mode: str,
    ) -> None:
        self.keepalive_calls.append((task_id, ld_instance_id, acquisition_mode))


def _build_request(
    connections: list[SourceConnectionData] | None = None,
) -> SourceAcquisitionRequest:
    return SourceAcquisitionRequest(
        request_id="request-1",
        task_id=101,
        execution=AcquisitionExecutionOptions(
            protocol="opcua",
            transport="tcp",
            acquisition_mode="SUBSCRIBE",
            interval_ms=100,
            max_iteration=None,
            request_timeout_ms=500,
            freshness_timeout_ms=30000,
            alive_timeout_ms=60000,
        ),
        connections=(
            connections
            if connections is not None
            else [
                SourceConnectionData("127.0.0.1", 4840, "IED_01", "LD_01", "urn:test"),
                SourceConnectionData("127.0.0.2", 4841, "IED_02", "LD_02", "urn:test"),
            ]
        ),
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


def test_start_returns_sessions_for_each_connection() -> None:
    async def _run() -> None:
        port = FakeSourceAcquisitionPort()
        state_cache_port = FakeStateCachePort()
        role = SubscriptionAcquisitionRole(
            acquisition_port=cast(SourceAcquisitionPort, port),
            state_cache_port=cast(SourceStateCachePort, state_cache_port),
        )

        request = _build_request()
        start_result = await role.start(request)

        assert isinstance(start_result, SubscriptionAcquisitionStartResult)
        assert start_result.request_id == request.request_id
        assert start_result.task_id == request.task_id
        assert len(start_result.sessions) == 2
        assert all(
            isinstance(session, SubscriptionAcquisitionSession) for session in start_result.sessions
        )
        assert state_cache_port.calls == []
        assert len(port.start_calls) == 2

    asyncio.run(_run())


def test_start_returns_empty_list_when_connections_are_empty() -> None:
    async def _run() -> None:
        role = SubscriptionAcquisitionRole(
            acquisition_port=cast(SourceAcquisitionPort, FakeSourceAcquisitionPort()),
            state_cache_port=cast(SourceStateCachePort, FakeStateCachePort()),
        )

        request = _build_request(connections=[])
        start_result = await role.start(request)

        assert start_result.request_id == request.request_id
        assert start_result.task_id == request.task_id
        assert start_result.sessions == []

    asyncio.run(_run())


def test_each_handler_uses_its_bound_connection_model_id() -> None:
    async def _run() -> None:
        port = FakeSourceAcquisitionPort()
        state_cache_port = FakeStateCachePort()
        diagnostics_role = FakeDiagnosticsRole()
        role = SubscriptionAcquisitionRole(
            acquisition_port=cast(SourceAcquisitionPort, port),
            state_cache_port=cast(SourceStateCachePort, state_cache_port),
            diagnostics_role=cast(RuntimeDiagnosticsRole, diagnostics_role),
        )

        request = _build_request()
        start_result = await role.start(request)

        assert start_result.request_id == request.request_id
        assert start_result.task_id == request.task_id

        first_handler = port.start_calls[0][3]
        second_handler = port.start_calls[1][3]

        await first_handler(_build_states("LD_01", "42.0"))
        await second_handler(_build_states("LD_02", "43.0"))

        assert state_cache_port.calls[0][0] == "LD_01"
        assert state_cache_port.calls[1][0] == "LD_02"
        assert diagnostics_role.keepalive_calls == [
            (101, 0, "SUBSCRIBE"),
            (101, 0, "SUBSCRIBE"),
        ]

    asyncio.run(_run())


def test_handler_uses_mode_aware_cache_when_available() -> None:
    async def _run() -> None:
        port = FakeSourceAcquisitionPort()
        state_cache_port = FakeModeAwareStateCachePort()
        role = SubscriptionAcquisitionRole(
            acquisition_port=cast(SourceAcquisitionPort, port),
            state_cache_port=cast(SourceStateCachePort, state_cache_port),
        )

        await role.start(_build_request(connections=_build_request().connections[:1]))
        handler = port.start_calls[0][3]
        await handler(_build_states("LD_01", "42.0"))

        assert len(state_cache_port.calls) == 1
        assert state_cache_port.calls[0][0] == "SUBSCRIBE"
        assert state_cache_port.calls[0][1] == "LD_01"
        assert len(state_cache_port.calls[0][2]) == 1

    asyncio.run(_run())


def test_session_close_is_idempotent() -> None:
    async def _run() -> None:
        port = FakeSourceAcquisitionPort()
        role = SubscriptionAcquisitionRole(
            acquisition_port=cast(SourceAcquisitionPort, port),
            state_cache_port=cast(SourceStateCachePort, FakeStateCachePort()),
        )

        start_result = await role.start(_build_request())
        await start_result.sessions[0].close()
        await start_result.sessions[0].close()

        assert port.handles[0].close_calls == 1
        assert port.handles[1].close_calls == 0

    asyncio.run(_run())
