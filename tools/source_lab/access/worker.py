# mypy: disable-error-code=import-untyped
"""Worker execution helpers for capacity scan."""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import Awaitable, Callable, Sequence
from concurrent.futures import ProcessPoolExecutor

from whale.shared.source.access import SourceAccessAdapter, build_source_access_adapter
from whale.shared.source.access.model import TickResult
from whale.shared.source.scheduling import (
    PollingErrorEvent,
    PollingJobSpec,
    PollingResultEvent,
    ReadConcurrencyLimiter,
    SourcePollingScheduler,
)
from tools.source_lab.access.metrics import (
    ReaderStats,
    WorkerRawStats,
    build_level_metrics,
    record_tick,
)
from tools.source_lab.access.model import CapacityLevelMetrics, CapacityScanConfig
from tools.source_lab.access.providers.base import SourceRuntimeSpec
from tools.source_lab.access.reporter import print_measurement_progress
from tools.source_lab.access.scheduling import (
    SourceReadSpec,
    build_source_specs,
    partition_specs_round_robin,
    resolve_mp_context,
)


async def run_worker_level(
    specs: Sequence[SourceReadSpec],
    *,
    target_hz: float,
    server_count: int,
    worker_index: int,
    config: CapacityScanConfig,
) -> WorkerRawStats:
    """Run one capacity level for one worker bucket."""

    readers = tuple(
        build_source_access_adapter(
            config.protocol,
            spec.source.endpoint,
            spec.source.points,
            read_timeout_s=config.read_timeout_s,
            opcua_client_backend=config.opcua_client_backend,
        )
        for spec in specs
    )
    reader_stats = [ReaderStats() for _ in readers]
    if not specs:
        return WorkerRawStats(
            worker_index=worker_index,
            reader_count=0,
            batch_mismatches=0,
            read_errors=0,
            missing_response_timestamps=0,
            response_timestamps_by_reader=(),
            max_observed_concurrent_reads=0,
        )

    expected_value_count = len(specs[0].source.points)
    interval_seconds = 1.0 / target_hz

    limiter = ReadConcurrencyLimiter[TickResult](max_concurrent=config.max_concurrent_reads)
    scheduler = SourcePollingScheduler[TickResult](limiter=limiter, diagnostics_enabled=False)
    loop = asyncio.get_running_loop()
    measure_start_at = loop.time() + config.warmup_s
    measure_end_at = measure_start_at + config.level_duration_s
    progress_task: asyncio.Task[None] | None = None

    async def _run_bounded(
        adapters: Sequence[SourceAccessAdapter],
        action: Callable[[SourceAccessAdapter], Awaitable[None]],
    ) -> None:
        semaphore = asyncio.Semaphore(max(1, min(config.max_concurrent_reads, 8)))

        async def run_one(adapter: SourceAccessAdapter) -> None:
            async with semaphore:
                await asyncio.wait_for(action(adapter), timeout=max(config.read_timeout_s, 10.0))

        await asyncio.gather(*(run_one(adapter) for adapter in adapters))

    def make_result_handler(
        reader_id: int,
    ) -> Callable[[PollingResultEvent[TickResult]], Awaitable[None]]:
        async def on_result(event: PollingResultEvent[TickResult]) -> None:
            if measure_start_at <= event.finished_at <= measure_end_at:
                record_tick(reader_stats[reader_id], event.result)

        return on_result

    def make_error_handler(reader_id: int) -> Callable[[PollingErrorEvent], Awaitable[None]]:
        async def on_error(event: PollingErrorEvent) -> None:
            if measure_start_at <= event.finished_at <= measure_end_at:
                record_tick(
                    reader_stats[reader_id],
                    TickResult(False, 0, event.duration_ms, None, event.error_type),
                )

        return on_error

    async def _report_progress() -> None:
        while True:
            await asyncio.sleep(config.progress_interval_s)
            now = loop.time()
            if now < measure_start_at:
                continue
            elapsed_s = min(config.level_duration_s, now - measure_start_at)
            ticks = sum(item.total_reads for item in reader_stats)
            bad = sum(item.batch_mismatches for item in reader_stats)
            print_measurement_progress(
                config,
                server_count=server_count,
                target_hz=target_hz,
                elapsed_s=elapsed_s,
                ticks=ticks,
                bad=bad,
                worker_index=worker_index if config.process_count > 1 else None,
            )
            if now >= measure_end_at:
                return

    await _run_bounded(readers, lambda adapter: adapter.connect())
    await _run_bounded(readers, lambda adapter: adapter.prepare_read())
    try:
        for index, (adapter, spec) in enumerate(zip(readers, specs)):
            scheduler.add_job(
                PollingJobSpec[TickResult](
                    job_id=f"capacity-reader-{spec.global_index}",
                    interval_seconds=interval_seconds,
                    offset_seconds=spec.offset_seconds,
                    timeout_seconds=config.read_timeout_s,
                    operation=lambda adapter=adapter: adapter.read_tick(
                        expected_value_count=expected_value_count
                    ),
                    on_result=make_result_handler(index),
                    on_error=make_error_handler(index),
                )
            )
        await scheduler.start()
        if config.progress_enabled and config.progress_interval_s > 0:
            progress_task = asyncio.create_task(_report_progress())
        try:
            await asyncio.sleep(config.warmup_s + config.level_duration_s)
        finally:
            if progress_task is not None:
                progress_task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await progress_task
            await scheduler.stop()
    finally:
        await _run_bounded(readers, lambda adapter: adapter.close())

    concurrency = await limiter.snapshot()
    return WorkerRawStats(
        worker_index=worker_index,
        reader_count=len(readers),
        batch_mismatches=sum(item.batch_mismatches for item in reader_stats),
        read_errors=sum(item.read_errors for item in reader_stats),
        missing_response_timestamps=sum(item.missing_response_timestamps for item in reader_stats),
        response_timestamps_by_reader=tuple(tuple(item.response_timestamps) for item in reader_stats),
        max_observed_concurrent_reads=concurrency.max_observed_active,
    )


def run_worker_entry(
    worker_index: int,
    specs: tuple[SourceReadSpec, ...],
    target_hz: float,
    server_count: int,
    config: CapacityScanConfig,
) -> WorkerRawStats:
    """Sync worker entrypoint for ProcessPoolExecutor."""

    return asyncio.run(
        run_worker_level(
            specs,
            target_hz=target_hz,
            server_count=server_count,
            worker_index=worker_index,
            config=config,
        )
    )


def run_level_once(
    sources: Sequence[SourceRuntimeSpec],
    *,
    target_hz: float,
    config: CapacityScanConfig,
) -> CapacityLevelMetrics:
    """Run one (server_count, hz) level and build aggregate metrics."""

    specs = build_source_specs(sources, target_hz=target_hz)
    partitions = partition_specs_round_robin(specs, process_count=config.process_count)

    if config.process_count == 1:
        worker_stats = [
            asyncio.run(
                run_worker_level(
                    partitions[0],
                    target_hz=target_hz,
                    server_count=len(sources),
                    worker_index=0,
                    config=config,
                )
            )
        ]
    else:
        with ProcessPoolExecutor(
            max_workers=config.process_count,
            mp_context=resolve_mp_context(),
        ) as executor:
            futures = [
                executor.submit(run_worker_entry, index, bucket, target_hz, len(sources), config)
                for index, bucket in enumerate(partitions)
                if bucket
            ]
            worker_stats = [future.result() for future in futures]

    return build_level_metrics(worker_stats, server_count=len(sources), target_hz=target_hz, config=config)
