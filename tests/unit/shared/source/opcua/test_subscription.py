"""Unit tests for OPC UA subscription handler behavior."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

import pytest

from whale.shared.source.models import Batch
from whale.shared.source.opcua.subscription import OpcUaSubscriptionHandler


class _FakeReader:
    """Small reader stub for subscription handler tests."""

    def __init__(self, batch: Batch | Exception) -> None:
        self._batch = batch
        self._publish_interval_ms = 10
        self.read_calls: list[tuple[tuple[str, ...], str]] = []

    async def read(self, addresses: tuple[str, ...], *, mode: str) -> Batch:
        self.read_calls.append((addresses, mode))
        if isinstance(self._batch, Exception):
            raise self._batch
        return self._batch


def _valid_batch(*, label: str = "baseline") -> Batch:
    """Build one frozen batch fixture."""

    return Batch(
        changes=(),
        batch_observed_at=datetime(2026, 5, 15, 10, 0, tzinfo=UTC),
        client_received_at=datetime(2026, 5, 15, 10, 0, tzinfo=UTC),
        availability_status="VALID",
        attributes={label: True},
    )


@pytest.mark.unit
def test_network_monitor_emits_new_stale_batch_without_mutating_frozen_batch() -> None:
    """Lag recovery should build a new STALE batch instead of mutating the original batch."""

    async def _run() -> None:
        baseline_batch = _valid_batch()
        reader = _FakeReader(baseline_batch)
        received_batches: list[Batch] = []

        handler = OpcUaSubscriptionHandler(
            received_batches.append,
            reader=reader,
            addresses=("s=IED001.LD0.WPPD1.TotW",),
        )
        handler._max_lag_ms = 0  # noqa: SLF001
        handler._sleep_interval_s = 0.001  # noqa: SLF001
        handler._last_received_at = datetime.now(UTC) - timedelta(seconds=1)  # noqa: SLF001

        await asyncio.sleep(0.01)

        assert received_batches
        stale_batch = received_batches[-1]
        assert stale_batch is not baseline_batch
        assert baseline_batch.availability_status == "VALID"
        assert stale_batch.availability_status == "STALE"
        assert stale_batch.attributes["baseline"] is True
        assert stale_batch.attributes["reason"] == "subscription_lag_detected"
        assert reader.read_calls[-1] == (("s=IED001.LD0.WPPD1.TotW",), "full")

        await handler.close()

    asyncio.run(_run())


@pytest.mark.unit
def test_network_monitor_emits_offline_batch_when_health_check_read_fails() -> None:
    """Lag recovery failures should emit an OFFLINE batch with failure metadata."""

    async def _run() -> None:
        received_batches: list[Batch] = []
        reader = _FakeReader(RuntimeError("offline"))

        handler = OpcUaSubscriptionHandler(
            received_batches.append,
            reader=reader,
            addresses=("s=IED001.LD0.WPPD1.TotW",),
        )
        handler._max_lag_ms = 0  # noqa: SLF001
        handler._sleep_interval_s = 0.001  # noqa: SLF001
        handler._last_received_at = datetime.now(UTC) - timedelta(seconds=1)  # noqa: SLF001

        await asyncio.sleep(0.01)

        assert received_batches
        offline_batch = received_batches[-1]
        assert offline_batch.availability_status == "OFFLINE"
        assert offline_batch.attributes["reason"] == "health_check_or_baseline_read_failed"
        assert offline_batch.attributes["exception"] == "offline"

        await handler.close()

    asyncio.run(_run())


@pytest.mark.unit
def test_network_monitor_uses_empty_health_check_when_addresses_missing() -> None:
    """Without saved addresses, lag recovery should fall back to an empty health-check read."""

    async def _run() -> None:
        received_batches: list[Batch] = []
        reader = _FakeReader(_valid_batch(label="health"))

        handler = OpcUaSubscriptionHandler(received_batches.append, reader=reader)
        handler._max_lag_ms = 0  # noqa: SLF001
        handler._sleep_interval_s = 0.001  # noqa: SLF001
        handler._last_received_at = datetime.now(UTC) - timedelta(seconds=1)  # noqa: SLF001

        await asyncio.sleep(0.01)

        assert reader.read_calls[-1] == ((), "full")
        await handler.close()

    asyncio.run(_run())


@pytest.mark.unit
def test_close_cancels_monitor_task_without_leaking_cancelled_error() -> None:
    """close should cancel the background monitor task cleanly."""

    async def _run() -> None:
        handler = OpcUaSubscriptionHandler(lambda batch: None, reader=_FakeReader(_valid_batch()))
        assert handler._monitor_task is not None  # noqa: SLF001
        await handler.close()
        assert handler._monitor_task.done()  # noqa: SLF001

    asyncio.run(_run())


@pytest.mark.unit
def test_emit_batch_logs_callback_exception_and_monitor_can_continue() -> None:
    """Ordinary callback failures should be logged without killing the monitor path."""

    async def _run() -> None:
        calls: list[Batch] = []

        def _bad_callback(batch: Batch) -> None:
            calls.append(batch)
            raise RuntimeError("boom")

        handler = OpcUaSubscriptionHandler(_bad_callback)
        batch = _valid_batch()

        with patch("whale.shared.source.opcua.subscription.logger.exception") as log_mock:
            await handler._emit_batch(batch)  # noqa: SLF001
            await handler._emit_batch(batch)  # noqa: SLF001

        assert len(calls) == 2
        assert log_mock.call_count == 2

        await handler.close()

    asyncio.run(_run())


@pytest.mark.unit
def test_dispatch_pending_emits_valid_batch() -> None:
    """Pending data changes should flush into one VALID batch."""

    async def _run() -> None:
        received_batches: list[Batch] = []
        handler = OpcUaSubscriptionHandler(received_batches.append)

        node = SimpleNamespace(nodeid=SimpleNamespace(to_string=lambda: "ns=2;s=A.B.C"))
        data = SimpleNamespace(
            monitored_item=SimpleNamespace(
                Value=SimpleNamespace(
                    StatusCode="Good",
                    SourceTimestamp=datetime(2026, 5, 15, 10, 0, tzinfo=UTC),
                    ServerTimestamp=datetime(2026, 5, 15, 10, 0, tzinfo=UTC),
                )
            )
        )

        handler.datachange_notification(node, 1, data)
        await handler._dispatch_pending()  # noqa: SLF001

        assert received_batches
        batch = received_batches[-1]
        assert batch.availability_status == "VALID"
        assert len(batch.changes) == 1
        assert batch.changes[0].node_key == "ns=2;s=A.B.C"

        await handler.close()

    asyncio.run(_run())


@pytest.mark.unit
def test_deduplicate_keeps_highest_client_sequence_per_node() -> None:
    """Deduplication should keep the latest change for each node key."""

    source_timestamp = datetime(2026, 5, 15, 10, 0, tzinfo=UTC)
    older = SimpleNamespace(
        node_key="A",
        client_sequence=1,
        source_timestamp=source_timestamp,
    )
    newer = SimpleNamespace(
        node_key="A",
        client_sequence=2,
        source_timestamp=source_timestamp + timedelta(seconds=1),
    )
    other = SimpleNamespace(
        node_key="B",
        client_sequence=1,
        source_timestamp=source_timestamp + timedelta(seconds=2),
    )

    deduped, observed = OpcUaSubscriptionHandler._deduplicate_and_observed(  # noqa: SLF001
        [older, newer, other]  # type: ignore[list-item]
    )

    assert len(deduped) == 2
    latest_by_key = {item.node_key: item for item in deduped}
    assert latest_by_key["A"].client_sequence == 2
    assert latest_by_key["B"].client_sequence == 1
    assert observed == source_timestamp
