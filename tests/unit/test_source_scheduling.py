"""Unit tests for the worker-local source polling kernel."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from whale.shared.source.scheduling import (
    PollingErrorEvent,
    PollingJobSpec,
    PollingJobStats,
    PollingResultEvent,
    ReadConcurrencyLimiter,
    SourcePollingScheduler,
    assign_even_stagger,
    build_even_stagger_offsets,
    build_stagger_assignments,
)
from whale.shared.source.scheduling.fixed_rate import HighFrequencyFixedRateScheduler


def test_read_concurrency_limiter_rejects_non_positive_max_concurrent() -> None:
    """Limiter must reject non-positive worker-local concurrency ceilings."""

    with pytest.raises(ValueError):
        ReadConcurrencyLimiter[int](max_concurrent=0)


def test_read_concurrency_limiter_run_returns_operation_result() -> None:
    """Limiter should preserve the simple run API."""

    async def scenario() -> None:
        limiter = ReadConcurrencyLimiter[int](max_concurrent=1)

        async def return_one() -> int:
            await asyncio.sleep(0.001)
            return 1

        result = await limiter.run(return_one)
        snapshot = await limiter.snapshot()

        assert result == 1
        assert snapshot.max_observed_active <= limiter.max_concurrent
        assert snapshot.active == 0

    asyncio.run(scenario())


def test_read_concurrency_limiter_snapshot_and_reset_counters_keep_async_api() -> None:
    """Limiter snapshot/reset should remain awaitable after lock removal."""

    async def scenario() -> None:
        limiter = ReadConcurrencyLimiter[int](max_concurrent=2)

        async def hold_slot(started: asyncio.Event, release: asyncio.Event) -> int:
            started.set()
            await release.wait()
            return 1

        started = asyncio.Event()
        release = asyncio.Event()
        task = asyncio.create_task(limiter.run(lambda: hold_slot(started, release)))
        await started.wait()

        snapshot_during_run = await limiter.snapshot()
        assert snapshot_during_run.active == 1
        assert snapshot_during_run.total_started == 1

        await limiter.reset_counters()
        reset_snapshot = await limiter.snapshot()
        assert reset_snapshot.active == 1
        assert reset_snapshot.max_observed_active == 1
        assert reset_snapshot.total_started == 0
        assert reset_snapshot.total_finished == 0

        release.set()
        await task
        final_snapshot = await limiter.snapshot()
        assert final_snapshot.active == 0
        assert final_snapshot.total_finished == 1

    asyncio.run(scenario())


def test_read_concurrency_limiter_recovers_active_count_after_exception() -> None:
    """Limiter should release its local slot even when the operation fails."""

    async def scenario() -> None:
        limiter = ReadConcurrencyLimiter[int](max_concurrent=1)

        async def fail() -> int:
            await asyncio.sleep(0.001)
            raise RuntimeError("boom")

        with pytest.raises(RuntimeError):
            await limiter.run(fail)

        snapshot = await limiter.snapshot()
        assert snapshot.active == 0
        assert snapshot.total_started == snapshot.total_finished

    asyncio.run(scenario())


def test_read_concurrency_limiter_respects_max_observed_active_under_parallel_load() -> None:
    """Limiter counters should stay within the configured concurrency ceiling."""

    async def scenario() -> None:
        limiter = ReadConcurrencyLimiter[int](max_concurrent=2)
        release = asyncio.Event()
        started = 0

        async def operation() -> int:
            nonlocal started
            started += 1
            await release.wait()
            return started

        tasks = [asyncio.create_task(limiter.run(operation)) for _ in range(4)]
        await asyncio.sleep(0.01)

        snapshot = await limiter.snapshot()
        assert snapshot.active <= limiter.max_concurrent
        assert snapshot.max_observed_active <= limiter.max_concurrent

        release.set()
        await asyncio.gather(*tasks)

    asyncio.run(scenario())


def test_polling_job_spec_validates_local_scheduler_fields() -> None:
    """Job spec should reject invalid worker-local polling configuration."""

    async def operation() -> int:
        return 1

    async def on_result(event: PollingResultEvent[int]) -> None:
        return None

    async def on_error(event: PollingErrorEvent) -> None:
        return None

    with pytest.raises(ValueError):
        PollingJobSpec(
            job_id="job",
            interval_seconds=0.0,
            operation=operation,
            on_result=on_result,
            on_error=on_error,
        )

    with pytest.raises(ValueError):
        PollingJobSpec(
            job_id="job",
            interval_seconds=0.1,
            offset_seconds=-0.1,
            operation=operation,
            on_result=on_result,
            on_error=on_error,
        )

    with pytest.raises(ValueError):
        PollingJobSpec(
            job_id="job",
            interval_seconds=0.1,
            timeout_seconds=0.0,
            operation=operation,
            on_result=on_result,
            on_error=on_error,
        )

    with pytest.raises(ValueError):
        PollingJobSpec(
            job_id="job",
            interval_seconds=0.1,
            operation=operation,
            on_result=on_result,
            on_error=on_error,
            overrun_policy="invalid",  # type: ignore[arg-type]
        )


def test_source_polling_scheduler_rejects_duplicate_and_late_add_job() -> None:
    """Scheduler should only accept unique jobs before startup."""

    async def operation() -> int:
        return 1

    async def on_result(event: PollingResultEvent[int]) -> None:
        return None

    async def on_error(event: PollingErrorEvent) -> None:
        return None

    spec = PollingJobSpec(
        job_id="job-1",
        interval_seconds=0.01,
        operation=operation,
        on_result=on_result,
        on_error=on_error,
    )

    scheduler = SourcePollingScheduler[int]()
    scheduler.add_job(spec)

    with pytest.raises(ValueError):
        scheduler.add_job(spec)

    async def scenario() -> None:
        await scheduler.start()
        try:
            with pytest.raises(RuntimeError):
                scheduler.add_job(
                    PollingJobSpec(
                        job_id="job-2",
                        interval_seconds=0.01,
                        operation=operation,
                        on_result=on_result,
                        on_error=on_error,
                    )
                )
        finally:
            await scheduler.stop()

    asyncio.run(scenario())


def test_source_polling_scheduler_result_event_and_stats_include_timing() -> None:
    """Successful ticks should expose scheduler timing and accumulate stats."""

    async def scenario() -> None:
        limiter = ReadConcurrencyLimiter[int](max_concurrent=1)
        scheduler = SourcePollingScheduler[int](
            limiter=limiter,
            diagnostics_enabled=True,
        )
        results: list[PollingResultEvent[int]] = []

        async def operation() -> int:
            await asyncio.sleep(0.003)
            return 7

        async def on_result(event: PollingResultEvent[int]) -> None:
            results.append(event)

        async def on_error(event: PollingErrorEvent) -> None:
            raise AssertionError(f"unexpected error: {event}")

        scheduler.add_job(
            PollingJobSpec(
                job_id="job-1",
                interval_seconds=0.01,
                operation=operation,
                on_result=on_result,
                on_error=on_error,
            )
        )

        await scheduler.start()
        try:
            await asyncio.sleep(0.05)
        finally:
            await scheduler.stop()

        assert results
        first = results[0]
        assert first.scheduled_delay_ms >= 0.0

        stats = scheduler.job_stats()[0]
        assert stats.success_count >= 1
        assert stats.last_scheduled_at is not None
        assert stats.last_scheduled_delay_ms is not None
        assert stats.max_scheduled_delay_ms >= 0.0

    asyncio.run(scenario())


def test_source_polling_scheduler_started_at_tracks_actual_operation_start() -> None:
    """started_at should reflect post-limiter operation start, not queue entry time."""

    async def scenario() -> None:
        limiter = ReadConcurrencyLimiter[str](max_concurrent=1)
        scheduler = SourcePollingScheduler[str](
            limiter=limiter,
            diagnostics_enabled=True,
        )
        results: dict[str, PollingResultEvent[str]] = {}

        async def slow_operation() -> str:
            await asyncio.sleep(0.03)
            return "slow"

        async def fast_operation() -> str:
            return "fast"

        async def on_result(event: PollingResultEvent[str]) -> None:
            results[event.job_id] = event

        async def on_error(event: PollingErrorEvent) -> None:
            raise AssertionError(f"unexpected error: {event}")

        scheduler.add_job(
            PollingJobSpec(
                job_id="slow",
                interval_seconds=1.0,
                offset_seconds=0.0,
                operation=slow_operation,
                on_result=on_result,
                on_error=on_error,
            )
        )
        scheduler.add_job(
            PollingJobSpec(
                job_id="fast",
                interval_seconds=1.0,
                offset_seconds=0.001,
                operation=fast_operation,
                on_result=on_result,
                on_error=on_error,
            )
        )

        await scheduler.start()
        try:
            await asyncio.sleep(0.08)
        finally:
            await scheduler.stop()

        slow_event = results["slow"]
        fast_event = results["fast"]
        assert slow_event.started_at >= slow_event.scheduled_at
        assert fast_event.started_at >= fast_event.scheduled_at
        assert fast_event.scheduled_delay_ms >= 20.0
        assert fast_event.started_at >= slow_event.finished_at

    asyncio.run(scenario())


def test_source_polling_scheduler_slow_callback_does_not_block_future_ticks() -> None:
    """Slow callbacks should not consume the next tick's scheduling budget."""

    async def scenario() -> None:
        scheduler = SourcePollingScheduler[int](diagnostics_enabled=True)
        results: list[PollingResultEvent[int]] = []

        async def operation() -> int:
            return 1

        async def on_result(event: PollingResultEvent[int]) -> None:
            results.append(event)
            await asyncio.sleep(0.04)

        async def on_error(event: PollingErrorEvent) -> None:
            raise AssertionError(f"unexpected error: {event}")

        scheduler.add_job(
            PollingJobSpec(
                job_id="job-1",
                interval_seconds=0.01,
                operation=operation,
                on_result=on_result,
                on_error=on_error,
            )
        )

        await scheduler.start()
        try:
            await asyncio.sleep(0.07)
        finally:
            await scheduler.stop()

        assert len(results) >= 1
        assert scheduler.job_stats()[0].success_count >= 4

    asyncio.run(scenario())


def test_source_polling_scheduler_without_diagnostics_keeps_default_stats_and_returns_raw_result() -> None:
    """Scheduler should emit results without interpreting status-like payload fields."""

    async def scenario() -> None:
        scheduler = SourcePollingScheduler[dict[str, object]](diagnostics_enabled=False)
        results: list[PollingResultEvent[dict[str, object]]] = []
        errors: list[PollingErrorEvent] = []
        payload = {"ok": False, "error_reason": "read_failed"}

        async def operation() -> dict[str, object]:
            return payload

        async def on_result(event: PollingResultEvent[dict[str, object]]) -> None:
            results.append(event)

        async def on_error(event: PollingErrorEvent) -> None:
            errors.append(event)

        scheduler.add_job(
            PollingJobSpec(
                job_id="job-1",
                interval_seconds=0.01,
                operation=operation,
                on_result=on_result,
                on_error=on_error,
            )
        )

        await scheduler.start()
        try:
            await asyncio.sleep(0.03)
        finally:
            await scheduler.stop()

        assert results
        assert not errors
        assert results[0].result is payload
        assert results[0].scheduled_delay_ms >= 0.0

        stats = scheduler.job_stats()[0]
        assert stats == PollingJobStats(
            job_id="job-1",
            success_count=0,
            error_count=0,
            timeout_count=0,
            skipped_tick_count=0,
            late_start_count=0,
            overrun_count=0,
            last_scheduled_at=None,
            last_started_at=None,
            last_finished_at=None,
            last_duration_ms=None,
            last_scheduled_delay_ms=None,
            max_scheduled_delay_ms=0.0,
        )

    asyncio.run(scenario())


def test_source_polling_scheduler_does_not_treat_result_ok_false_as_error() -> None:
    """Scheduler should route normal returns to on_result even when result.ok is false."""

    async def scenario() -> None:
        scheduler = SourcePollingScheduler[SimpleNamespace](diagnostics_enabled=False)
        results: list[PollingResultEvent[SimpleNamespace]] = []
        errors: list[PollingErrorEvent] = []

        async def operation() -> SimpleNamespace:
            return SimpleNamespace(ok=False, error_reason="timeout")

        async def on_result(event: PollingResultEvent[SimpleNamespace]) -> None:
            results.append(event)

        async def on_error(event: PollingErrorEvent) -> None:
            errors.append(event)

        scheduler.add_job(
            PollingJobSpec(
                job_id="job-1",
                interval_seconds=0.01,
                operation=operation,
                on_result=on_result,
                on_error=on_error,
            )
        )

        await scheduler.start()
        try:
            await asyncio.sleep(0.03)
        finally:
            await scheduler.stop()

        assert results
        assert not errors
        assert results[0].result.ok is False

    asyncio.run(scenario())


def test_source_polling_scheduler_timeout_error_updates_stats() -> None:
    """Timed-out ticks should surface errors and increment timeout_count."""

    async def scenario() -> None:
        scheduler = SourcePollingScheduler[int](diagnostics_enabled=True)
        errors: list[PollingErrorEvent] = []

        async def operation() -> int:
            await asyncio.sleep(0.03)
            return 1

        async def on_result(event: PollingResultEvent[int]) -> None:
            raise AssertionError("unexpected success")

        async def on_error(event: PollingErrorEvent) -> None:
            errors.append(event)

        scheduler.add_job(
            PollingJobSpec(
                job_id="timeout-job",
                interval_seconds=0.01,
                timeout_seconds=0.005,
                operation=operation,
                on_result=on_result,
                on_error=on_error,
            )
        )

        await scheduler.start()
        try:
            await asyncio.sleep(0.04)
        finally:
            await scheduler.stop()

        assert errors
        first = errors[0]
        assert first.error_type == "TimeoutError"
        assert first.scheduled_delay_ms >= 0.0

        stats = scheduler.job_stats()[0]
        assert stats.error_count >= 1
        assert stats.timeout_count >= 1

    asyncio.run(scenario())


def test_high_frequency_fixed_rate_scheduler_emits_result_events() -> None:
    """Dedicated fixed-rate scheduler should emit result events on its direct path."""

    async def scenario() -> None:
        scheduler = HighFrequencyFixedRateScheduler[int]()
        events: list[PollingResultEvent[int]] = []

        async def operation() -> int:
            return 3

        async def on_result(event: PollingResultEvent[int]) -> None:
            events.append(event)

        async def on_error(event: PollingErrorEvent) -> None:
            raise AssertionError(f"unexpected error: {event}")

        scheduler._event_sink = lambda event: events.append(event)  # type: ignore[attr-defined]
        scheduler.add_job(
            PollingJobSpec(
                job_id="job-1",
                interval_seconds=0.01,
                operation=operation,
                on_result=on_result,
                on_error=on_error,
            )
        )

        await scheduler.start()
        try:
            await asyncio.sleep(0.03)
        finally:
            await scheduler.stop()

        assert events
        assert events[0].result == 3

    asyncio.run(scenario())


def test_source_polling_scheduler_exception_routes_to_on_error_without_diagnostics_stats() -> None:
    """Scheduler should only use on_error for raised exceptions."""

    async def scenario() -> None:
        scheduler = SourcePollingScheduler[int](diagnostics_enabled=False)
        errors: list[PollingErrorEvent] = []

        async def operation() -> int:
            raise RuntimeError("boom")

        async def on_result(event: PollingResultEvent[int]) -> None:
            raise AssertionError("unexpected success")

        async def on_error(event: PollingErrorEvent) -> None:
            errors.append(event)

        scheduler.add_job(
            PollingJobSpec(
                job_id="error-job",
                interval_seconds=0.01,
                operation=operation,
                on_result=on_result,
                on_error=on_error,
            )
        )

        await scheduler.start()
        try:
            await asyncio.sleep(0.03)
        finally:
            await scheduler.stop()

        assert errors
        assert errors[0].error_type == "RuntimeError"
        stats = scheduler.job_stats()[0]
        assert stats.error_count == 0
        assert stats.timeout_count == 0

    asyncio.run(scenario())


def test_source_polling_scheduler_exception_updates_stats_when_diagnostics_enabled() -> None:
    """Diagnostics mode should count raised operation failures."""

    async def scenario() -> None:
        scheduler = SourcePollingScheduler[int](diagnostics_enabled=True)
        errors: list[PollingErrorEvent] = []

        async def operation() -> int:
            raise RuntimeError("boom")

        async def on_result(event: PollingResultEvent[int]) -> None:
            raise AssertionError("unexpected success")

        async def on_error(event: PollingErrorEvent) -> None:
            errors.append(event)

        scheduler.add_job(
            PollingJobSpec(
                job_id="error-job",
                interval_seconds=0.01,
                operation=operation,
                on_result=on_result,
                on_error=on_error,
            )
        )

        await scheduler.start()
        try:
            await asyncio.sleep(0.03)
        finally:
            await scheduler.stop()

        assert errors
        stats = scheduler.job_stats()[0]
        assert stats.error_count > 0

    asyncio.run(scenario())


def test_source_polling_scheduler_timeout_without_diagnostics_keeps_default_timeout_stats() -> None:
    """Timeout events should still be emitted even when stats are disabled."""

    async def scenario() -> None:
        scheduler = SourcePollingScheduler[int](diagnostics_enabled=False)
        errors: list[PollingErrorEvent] = []

        async def operation() -> int:
            await asyncio.sleep(0.03)
            return 1

        async def on_result(event: PollingResultEvent[int]) -> None:
            raise AssertionError("unexpected success")

        async def on_error(event: PollingErrorEvent) -> None:
            errors.append(event)

        scheduler.add_job(
            PollingJobSpec(
                job_id="timeout-job",
                interval_seconds=0.01,
                timeout_seconds=0.005,
                operation=operation,
                on_result=on_result,
                on_error=on_error,
            )
        )

        await scheduler.start()
        try:
            await asyncio.sleep(0.04)
        finally:
            await scheduler.stop()

        assert errors
        assert errors[0].error_type == "TimeoutError"
        assert scheduler.job_stats()[0].timeout_count == 0

    asyncio.run(scenario())


def test_source_polling_scheduler_skip_missed_records_overrun() -> None:
    """Fixed-rate overrun should skip missed ticks and update local counters."""

    async def scenario() -> None:
        scheduler = SourcePollingScheduler[int](diagnostics_enabled=True)

        async def operation() -> int:
            await asyncio.sleep(0.02)
            return 1

        async def on_result(event: PollingResultEvent[int]) -> None:
            return None

        async def on_error(event: PollingErrorEvent) -> None:
            raise AssertionError(f"unexpected error: {event}")

        scheduler.add_job(
            PollingJobSpec(
                job_id="overrun-job",
                interval_seconds=0.005,
                operation=operation,
                on_result=on_result,
                on_error=on_error,
            )
        )

        await scheduler.start()
        try:
            await asyncio.sleep(0.06)
        finally:
            await scheduler.stop()

        stats = scheduler.job_stats()[0]
        assert stats.skipped_tick_count > 0 or stats.overrun_count > 0
        assert stats.overrun_count >= 1

    asyncio.run(scenario())


def test_source_polling_scheduler_skip_missed_without_diagnostics_keeps_default_stats() -> None:
    """Skip-missed overrun accounting should stay disabled on the lean path."""

    async def scenario() -> None:
        scheduler = SourcePollingScheduler[int](diagnostics_enabled=False)

        async def operation() -> int:
            await asyncio.sleep(0.05)
            return 1

        async def on_result(event: PollingResultEvent[int]) -> None:
            return None

        async def on_error(event: PollingErrorEvent) -> None:
            raise AssertionError(f"unexpected error: {event}")

        scheduler.add_job(
            PollingJobSpec(
                job_id="overrun-job",
                interval_seconds=0.01,
                operation=operation,
                on_result=on_result,
                on_error=on_error,
            )
        )

        await scheduler.start()
        try:
            await asyncio.sleep(0.08)
        finally:
            await scheduler.stop()

        stats = scheduler.job_stats()[0]
        assert stats.skipped_tick_count == 0
        assert stats.overrun_count == 0

    asyncio.run(scenario())


def test_build_even_stagger_offsets_and_assign_even_stagger_behave_deterministically() -> None:
    """Stagger helpers should preserve deterministic spacing and input order."""

    assert build_even_stagger_offsets(count=0, interval_seconds=1.0) == ()

    with pytest.raises(ValueError):
        build_even_stagger_offsets(count=4, interval_seconds=0.0)

    offsets = build_even_stagger_offsets(count=4, interval_seconds=1.0)
    assert offsets == (0.0, 0.25, 0.5, 0.75)

    assignments = build_stagger_assignments(count=4, interval_seconds=1.0)
    assert tuple(item.offset_seconds for item in assignments) == offsets

    assignments = assign_even_stagger(
        ("first", "second", "third"),
        interval_seconds=0.9,
    )
    assert tuple(item for item, _ in assignments) == ("first", "second", "third")
