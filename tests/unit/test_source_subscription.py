"""Unit tests for the shared OPC UA subscription handler skeleton."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any

import pytest

from whale.shared.source.models import Batch, NodeValueChange
from whale.shared.source.opcua.subscription import OpcUaSubscriptionHandler


class _FakeNodeId:
    def __init__(self, value: str) -> None:
        self._value = value

    def to_string(self) -> str:
        return self._value


class _FakeNode:
    def __init__(self, value: str) -> None:
        self.nodeid = _FakeNodeId(value)


class _FakeReader:
    def __init__(self, batch: Batch | Exception) -> None:
        self._batch = batch
        self._publish_interval_ms = 10
        self.read_calls: list[tuple[list[str], str]] = []

    async def read(self, addresses: list[str], *, mode: str) -> Batch:
        self.read_calls.append((addresses, mode))
        if isinstance(self._batch, Exception):
            raise self._batch
        return self._batch


def _change(
    node_key: str,
    *,
    value: Any,
    client_sequence: int,
    source_timestamp: datetime | None = None,
) -> NodeValueChange:
    return NodeValueChange(
        node_key=node_key,
        value=value,
        quality="Good",
        source_timestamp=source_timestamp,
        server_timestamp=source_timestamp,
        client_sequence=client_sequence,
        attributes={"source": "subscription"},
    )


def _data(value: Any, *, source_timestamp: datetime | None = None) -> object:
    return SimpleNamespace(
        monitored_item=SimpleNamespace(
            Value=SimpleNamespace(
                StatusCode="Good",
                SourceTimestamp=source_timestamp,
                ServerTimestamp=source_timestamp,
            )
        ),
        value=value,
    )


@pytest.mark.unit
def test_deduplicate_and_observed_returns_latest_per_node_and_earliest_timestamp() -> None:
    """Deduplicate by node_key, keep the highest client_sequence, and return the earliest source timestamp."""
    early = datetime(2026, 5, 12, 9, 0, tzinfo=UTC)
    later = datetime(2026, 5, 12, 9, 1, tzinfo=UTC)

    deduped, observed = OpcUaSubscriptionHandler._deduplicate_and_observed(
        [
            _change("ns=2;s=A", value=1, client_sequence=1, source_timestamp=later),
            _change("ns=2;s=A", value=2, client_sequence=2, source_timestamp=early),
            _change("ns=2;s=B", value=3, client_sequence=3, source_timestamp=later),
        ]
    )

    assert {change.node_key: change.value for change in deduped} == {"ns=2;s=A": 2, "ns=2;s=B": 3}
    assert observed == early


@pytest.mark.unit
def test_micro_batch_flush_deduplicates_and_sets_batch_observed_at() -> None:
    """Flush pending changes as one batch, deduplicate duplicate nodes, and keep the earliest observed time."""
    async def _run() -> None:
        received_batches: list[Batch] = []
        handler = OpcUaSubscriptionHandler(received_batches.append)
        first_seen = datetime(2026, 5, 12, 9, 10, tzinfo=UTC)

        handler._pending_subscription.extend(  # noqa: SLF001
            [
                _change("ns=2;s=A", value=1, client_sequence=1, source_timestamp=first_seen),
                _change("ns=2;s=A", value=2, client_sequence=2, source_timestamp=first_seen),
                _change(
                    "ns=2;s=B",
                    value=3,
                    client_sequence=3,
                    source_timestamp=first_seen + timedelta(seconds=1),
                ),
            ]
        )

        await handler._dispatch_pending()  # noqa: SLF001

        assert len(received_batches) == 1
        assert received_batches[0].availability_status == "VALID"
        assert received_batches[0].batch_observed_at == first_seen
        assert {change.node_key for change in received_batches[0].changes} == {"ns=2;s=A", "ns=2;s=B"}

    asyncio.run(_run())


@pytest.mark.unit
def test_datachange_notification_flushes_sync_callback_with_client_received_at() -> None:
    """Flush subscription changes through a sync callback and stamp client_received_at before invocation."""
    async def _run() -> None:
        callback_seen_at: list[datetime] = []
        received_batches: list[Batch] = []

        def _on_data_change(batch: Batch) -> None:
            callback_seen_at.append(datetime.now(UTC))
            received_batches.append(batch)

        handler = OpcUaSubscriptionHandler(_on_data_change)
        handler.datachange_notification(
            _FakeNode("ns=2;s=A"),
            10.0,
            _data(10.0, source_timestamp=datetime(2026, 5, 12, 9, 20, tzinfo=UTC)),
        )

        for _ in range(20):
            if received_batches:
                break
            await asyncio.sleep(0.001)

        assert len(received_batches) == 1
        assert received_batches[0].client_received_at <= callback_seen_at[0]
        assert received_batches[0].changes[0].attributes == {"source": "subscription"}

        await handler.close()

    asyncio.run(_run())


@pytest.mark.unit
def test_network_monitor_flushes_stale_batch_from_baseline_read() -> None:
    """Emit a STALE batch from baseline read when subscription traffic lags beyond the monitor threshold."""
    async def _run() -> None:
        baseline_batch = Batch(
            changes=(),
            batch_observed_at=datetime(2026, 5, 12, 9, 30, tzinfo=UTC),
            client_received_at=datetime(2026, 5, 12, 9, 30, tzinfo=UTC),
            availability_status="VALID",
        )
        received_batches: list[Batch] = []
        handler = OpcUaSubscriptionHandler(received_batches.append, reader=_FakeReader(baseline_batch))
        handler._max_lag_ms = 0  # noqa: SLF001
        handler._sleep_interval_s = 0.001  # noqa: SLF001
        handler._last_received_at = datetime.now(UTC) - timedelta(seconds=1)  # noqa: SLF001

        await asyncio.sleep(0.01)

        assert received_batches
        assert received_batches[-1].availability_status == "STALE"
        assert handler._reader.read_calls[-1] == ((), "full")  # noqa: SLF001

        await handler.close()

    asyncio.run(_run())


@pytest.mark.unit
def test_network_monitor_flushes_offline_batch_when_baseline_read_fails() -> None:
    """Emit an OFFLINE batch with baseline-read failure metadata when the recovery read raises."""
    async def _run() -> None:
        received_batches: list[Batch] = []
        handler = OpcUaSubscriptionHandler(
            received_batches.append,
            reader=_FakeReader(RuntimeError("offline")),
        )
        handler._max_lag_ms = 0  # noqa: SLF001
        handler._sleep_interval_s = 0.001  # noqa: SLF001
        handler._last_received_at = datetime.now(UTC) - timedelta(seconds=1)  # noqa: SLF001

        await asyncio.sleep(0.01)

        assert received_batches
        assert received_batches[-1].availability_status == "OFFLINE"
        assert received_batches[-1].attributes["reason"] == "baseline_read_failed"

        await handler.close()

    asyncio.run(_run())


@pytest.mark.unit
def test_async_callback_path_is_covered_by_dispatch() -> None:
    """Await async callbacks during flush so async and sync callback paths are both exercised."""
    async def _run() -> None:
        received_batches: list[Batch] = []

        async def _on_data_change(batch: Batch) -> None:
            received_batches.append(batch)

        handler = OpcUaSubscriptionHandler(_on_data_change)
        handler._pending_subscription.append(_change("ns=2;s=A", value=5, client_sequence=1))  # noqa: SLF001

        await handler._dispatch_pending()  # noqa: SLF001

        assert len(received_batches) == 1
        assert received_batches[0].availability_status == "VALID"

    asyncio.run(_run())


@pytest.mark.unit
def test_dispatch_pending_raises_timeout_when_callback_lock_is_held() -> None:
    """Raise a timeout when callback dispatch cannot acquire the lock within the configured deadline."""
    async def _run() -> None:
        handler = OpcUaSubscriptionHandler(lambda batch: None)
        handler._callback_lock_timeout = 0.001  # noqa: SLF001
        handler._pending_subscription.append(_change("ns=2;s=A", value=5, client_sequence=1))  # noqa: SLF001
        await handler._callback_lock.acquire()  # noqa: SLF001

        with pytest.raises(asyncio.TimeoutError):
            await handler._dispatch_pending()  # noqa: SLF001

        handler._callback_lock.release()  # noqa: SLF001
        await handler.close()

    asyncio.run(_run())
