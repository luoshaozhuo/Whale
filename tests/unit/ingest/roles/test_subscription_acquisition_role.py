"""Unit tests for the subscription acquisition role."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import cast

import pytest

from whale.ingest.ports.source.source_acquisition_port import (
    SourceAcquisitionPort,
    SourceSubscriptionHandle,
    SubscriptionStateHandler,
)
from whale.ingest.ports.state.source_state_cache_port import SourceStateCachePort
from whale.ingest.usecases.dtos.acquired_node_state import (
    AcquiredNodeStateBatch,
    AcquiredNodeValue,
)
from whale.ingest.usecases.dtos.source_acquisition_request import (
    AcquisitionExecutionOptions,
    AcquisitionItemData,
    SourceAcquisitionRequest,
)
from whale.ingest.usecases.dtos.source_connection_data import SourceConnectionData
from whale.ingest.usecases.roles.subscription_acquisition_role import (
    SubscriptionAcquisitionRole,
    SubscriptionAcquisitionSession,
)


class FakeHandle(SourceSubscriptionHandle):
    def __init__(self) -> None:
        self.close_calls = 0

    async def close(self) -> None:
        self.close_calls += 1


class FakeSourceAcquisitionPort:
    def __init__(
        self,
        *,
        baseline_by_ld_name: dict[str, AcquiredNodeStateBatch] | None = None,
        fail_on_start_index: int | None = None,
    ) -> None:
        self._baseline_by_ld_name = baseline_by_ld_name or {}
        self._fail_on_start_index = fail_on_start_index
        self.read_calls: list[str] = []
        self.start_calls: list[tuple[str, SubscriptionStateHandler]] = []
        self.handles: list[FakeHandle] = []

    async def read(
        self,
        execution: object,
        connection: SourceConnectionData,
        items: list[AcquisitionItemData],
    ) -> AcquiredNodeStateBatch:
        del execution, items
        self.read_calls.append(connection.ld_name)
        return self._baseline_by_ld_name[connection.ld_name]

    async def start_subscription(
        self,
        execution: AcquisitionExecutionOptions,
        connection: SourceConnectionData,
        items: list[AcquisitionItemData],
        *,
        state_received: SubscriptionStateHandler,
    ) -> SourceSubscriptionHandle:
        del execution, items
        call_index = len(self.start_calls)
        self.start_calls.append((connection.ld_name, state_received))
        if self._fail_on_start_index == call_index:
            raise RuntimeError("subscribe failed")

        handle = FakeHandle()
        self.handles.append(handle)
        return handle


class FakeStateCachePort:
    def __init__(self) -> None:
        self.update_calls: list[tuple[str, AcquiredNodeStateBatch]] = []
        self.mark_alive_calls: list[tuple[str, datetime]] = []
        self.mark_unavailable_calls: list[tuple[str, str, str | None]] = []

    def update(self, *, ld_name: str, batch: AcquiredNodeStateBatch) -> int:
        self.update_calls.append((ld_name, batch))
        return len(batch.values)

    def mark_alive(self, *, ld_name: str, observed_at: datetime) -> None:
        self.mark_alive_calls.append((ld_name, observed_at))

    def mark_unavailable(
        self,
        *,
        ld_name: str,
        status: str,
        observed_at: datetime,
        reason: str | None = None,
    ) -> None:
        del observed_at
        self.mark_unavailable_calls.append((ld_name, status, reason))


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


def _build_batch(source_id: str, value: str) -> AcquiredNodeStateBatch:
    now = datetime.now(tz=UTC)
    return AcquiredNodeStateBatch(
        source_id=source_id,
        batch_observed_at=now,
        client_received_at=now,
        client_processed_at=now,
        values=[AcquiredNodeValue(node_key="TotW", value=value)],
    )


def test_start_reads_baseline_before_starting_subscriptions() -> None:
    async def _run() -> None:
        port = FakeSourceAcquisitionPort(
            baseline_by_ld_name={
                "LD_01": _build_batch("LD_01", "1"),
                "LD_02": _build_batch("LD_02", "2"),
            }
        )
        cache = FakeStateCachePort()
        role = SubscriptionAcquisitionRole(
            acquisition_port=cast(SourceAcquisitionPort, port),
            state_cache_port=cast(SourceStateCachePort, cache),
        )

        start_result = await role.start(_build_request())

        assert len(start_result.sessions) == 2
        assert all(
            isinstance(session, SubscriptionAcquisitionSession)
            for session in start_result.sessions
        )
        assert port.read_calls == ["LD_01", "LD_02"]
        assert [call[0] for call in cache.update_calls] == ["LD_01", "LD_02"]
        assert [call[0] for call in cache.mark_alive_calls] == ["LD_01", "LD_02"]

    asyncio.run(_run())


def test_subscription_callback_updates_cache_for_bound_connection() -> None:
    async def _run() -> None:
        port = FakeSourceAcquisitionPort(
            baseline_by_ld_name={"LD_01": _build_batch("LD_01", "1")}
        )
        cache = FakeStateCachePort()
        role = SubscriptionAcquisitionRole(
            acquisition_port=cast(SourceAcquisitionPort, port),
            state_cache_port=cast(SourceStateCachePort, cache),
        )

        await role.start(_build_request(connections=_build_request().connections[:1]))
        handler = port.start_calls[0][1]
        await handler(_build_batch("LD_01", "42.0"))

        assert [call[0] for call in cache.update_calls] == ["LD_01", "LD_01"]
        assert cache.update_calls[-1][1].values[0].value == "42.0"
        assert [call[0] for call in cache.mark_alive_calls] == ["LD_01", "LD_01"]

    asyncio.run(_run())


def test_start_failure_marks_unavailable_and_closes_started_sessions() -> None:
    async def _run() -> None:
        port = FakeSourceAcquisitionPort(
            baseline_by_ld_name={
                "LD_01": _build_batch("LD_01", "1"),
                "LD_02": _build_batch("LD_02", "2"),
            },
            fail_on_start_index=1,
        )
        cache = FakeStateCachePort()
        role = SubscriptionAcquisitionRole(
            acquisition_port=cast(SourceAcquisitionPort, port),
            state_cache_port=cast(SourceStateCachePort, cache),
        )

        with pytest.raises(RuntimeError, match="subscribe failed"):
            await role.start(_build_request())

        assert cache.mark_unavailable_calls == [
            ("LD_02", "ERROR", "subscription start failed")
        ]
        assert len(port.handles) == 1
        assert port.handles[0].close_calls == 1

    asyncio.run(_run())


def test_session_close_is_idempotent() -> None:
    async def _run() -> None:
        port = FakeSourceAcquisitionPort(
            baseline_by_ld_name={"LD_01": _build_batch("LD_01", "1")}
        )
        role = SubscriptionAcquisitionRole(
            acquisition_port=cast(SourceAcquisitionPort, port),
            state_cache_port=cast(SourceStateCachePort, FakeStateCachePort()),
        )

        start_result = await role.start(_build_request(connections=_build_request().connections[:1]))
        await start_result.sessions[0].close()
        await start_result.sessions[0].close()

        assert port.handles[0].close_calls == 1

    asyncio.run(_run())
