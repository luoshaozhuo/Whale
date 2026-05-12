"""Unit tests for the polling acquisition role."""

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
from whale.ingest.usecases.roles.polling_acquisition_role import (
    PollingAcquisitionRole,
    PollingAcquisitionSession,
)


class FakeSourceAcquisitionPort:
    def __init__(
        self,
        *,
        batches_by_ld_name: dict[str, AcquiredNodeStateBatch] | None = None,
        error: Exception | None = None,
    ) -> None:
        self._batches_by_ld_name = batches_by_ld_name or {}
        self._error = error
        self.read_calls: list[str] = []

    async def read(
        self,
        execution: object,
        connection: SourceConnectionData,
        items: list[AcquisitionItemData],
    ) -> AcquiredNodeStateBatch:
        del execution, items
        self.read_calls.append(connection.ld_name)
        if self._error is not None:
            raise self._error
        return self._batches_by_ld_name[connection.ld_name]

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
    max_iteration: int | None = 1,
    connections: list[SourceConnectionData] | None = None,
) -> SourceAcquisitionRequest:
    return SourceAcquisitionRequest(
        request_id="request-1",
        task_id=101,
        execution=AcquisitionExecutionOptions(
            protocol="opcua",
            transport="tcp",
            acquisition_mode="POLLING",
            interval_ms=20,
            max_iteration=max_iteration,
            request_timeout_ms=500,
            freshness_timeout_ms=30000,
            alive_timeout_ms=60000,
        ),
        connections=connections if connections is not None else [_build_connection(1)],
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


def test_start_returns_session_and_reads_one_iteration() -> None:
    async def _run() -> None:
        port = FakeSourceAcquisitionPort(
            batches_by_ld_name={"LD_01": _build_batch("LD_01", "1")}
        )
        cache = FakeStateCachePort()
        role = PollingAcquisitionRole(
            acquisition_port=cast(SourceAcquisitionPort, port),
            state_cache_port=cast(SourceStateCachePort, cache),
        )

        start_result = role.start(_build_request())
        assert isinstance(start_result.sessions[0], PollingAcquisitionSession)

        await cast(PollingAcquisitionSession, start_result.sessions[0]).task

        assert port.read_calls == ["LD_01"]
        assert [call[0] for call in cache.update_calls] == ["LD_01"]
        assert [call[0] for call in cache.mark_alive_calls] == ["LD_01"]
        assert cache.mark_unavailable_calls == []

    asyncio.run(_run())


def test_empty_batch_skips_update_but_still_marks_alive() -> None:
    async def _run() -> None:
        now = datetime.now(tz=UTC)
        empty_batch = AcquiredNodeStateBatch(
            source_id="LD_01",
            batch_observed_at=now,
            client_received_at=now,
            client_processed_at=now,
            values=[],
        )
        cache = FakeStateCachePort()
        role = PollingAcquisitionRole(
            acquisition_port=cast(
                SourceAcquisitionPort,
                FakeSourceAcquisitionPort(batches_by_ld_name={"LD_01": empty_batch}),
            ),
            state_cache_port=cast(SourceStateCachePort, cache),
        )

        start_result = role.start(_build_request())
        await cast(PollingAcquisitionSession, start_result.sessions[0]).task

        assert cache.update_calls == []
        assert len(cache.mark_alive_calls) == 1

    asyncio.run(_run())


def test_read_error_marks_source_unavailable() -> None:
    async def _run() -> None:
        cache = FakeStateCachePort()
        role = PollingAcquisitionRole(
            acquisition_port=cast(
                SourceAcquisitionPort,
                FakeSourceAcquisitionPort(error=RuntimeError("boom")),
            ),
            state_cache_port=cast(SourceStateCachePort, cache),
        )

        start_result = role.start(_build_request())
        with pytest.raises(RuntimeError, match="boom"):
            await cast(PollingAcquisitionSession, start_result.sessions[0]).task

        assert cache.mark_unavailable_calls == [
            ("LD_01", "ERROR", "polling read failed")
        ]

    asyncio.run(_run())
