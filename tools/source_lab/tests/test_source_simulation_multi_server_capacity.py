"""Multi-server OPC UA polling capacity test.

Purpose:
- Find the sustainable boundary for a selected simulator backend and client backend.
- Scan server_count and sampling rate (Hz) with configurable start/step/max.
- Keep production read path intact: OpcUaSourceReader -> prepare_read -> read_prepared_raw.
- Do not run pyinstrument here; this file is for capacity only.

Typical run:
    SOURCE_SIM_OPCUA_BACKEND=open62541 \
    SOURCE_SIM_OPCUA_CLIENT_BACKEND=open62541 \
    SOURCE_SIM_LOAD_PROCESS_COUNT=1 \
    SOURCE_SIM_LOAD_COROUTINES_PER_PROCESS=10 \
    SOURCE_SIM_LOAD_SERVER_COUNT_START=1 \
    SOURCE_SIM_LOAD_SERVER_COUNT_STEP=4 \
    SOURCE_SIM_LOAD_SERVER_COUNT_MAX=30 \
    SOURCE_SIM_LOAD_HZ_START=5 \
    SOURCE_SIM_LOAD_HZ_STEP=5 \
    SOURCE_SIM_LOAD_HZ_MAX=30 \
    SOURCE_SIM_LOAD_LEVEL_DURATION_S=30 \
    SOURCE_SIM_LOAD_WARMUP_S=10 \
    SOURCE_SIM_LOAD_SOURCE_UPDATE_ENABLED=true \
    SOURCE_SIM_LOAD_SOURCE_UPDATE_HZ=10 \
    python -m pytest tools/source_lab/tests/test_source_simulation_multi_server_capacity.py -s -v
"""

from __future__ import annotations

import asyncio
import multiprocessing as mp
import os
import time
from collections.abc import Awaitable, Callable, Iterator, Sequence
from concurrent.futures import ProcessPoolExecutor
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime

import pytest

from whale.shared.source.models import SourceConnectionProfile
from whale.shared.source.opcua.backends import PreparedReadPlan
from whale.shared.source.opcua.reader import OpcUaSourceReader
from whale.shared.source.scheduling import (
    PollingErrorEvent,
    PollingJobSpec,
    PollingResultEvent,
    ReadConcurrencyLimiter,
    SourcePollingScheduler,
    build_even_stagger_offsets,
)
from tools.source_lab.opcua.address_space import logical_path
from tools.source_lab.model import SimulatedSource, UpdateConfig
from tools.source_lab.fleet import SourceSimulatorFleet
from tools.source_lab.tests.support.sources import (
    PortAllocator,
    build_multi_sources,
    build_opcua_endpoint,
    build_opcua_source_from_repository,
)


def _env_flag(name: str, default: bool) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() not in {"0", "false", "no", "off"}


def _env_int(name: str, default: int) -> int:
    value = os.environ.get(name)
    return default if value is None or value.strip() == "" else int(value)


def _env_float(name: str, default: float) -> float:
    value = os.environ.get(name)
    return default if value is None or value.strip() == "" else float(value)


def _env_first_int(names: Sequence[str], default: int) -> int:
    for name in names:
        value = os.environ.get(name)
        if value is not None and value.strip() != "":
            return int(value)
    return default


def _env_first_float(names: Sequence[str], default: float) -> float:
    for name in names:
        value = os.environ.get(name)
        if value is not None and value.strip() != "":
            return float(value)
    return default


def _iter_int_ramp(start: int, step: int, maximum: int) -> Iterator[int]:
    current = start
    while current <= maximum:
        yield current
        current += step


def _iter_float_ramp(start: float, step: float, maximum: float) -> Iterator[float]:
    current = start
    while current <= maximum + 1e-12:
        yield round(current, 10)
        current += step


def _raw_value_count(data_values: Sequence[object]) -> int:
    count = 0
    for item in data_values:
        if hasattr(item, "Value"):
            count += 1
        elif getattr(item, "value", None) is not None:
            count += 1
        elif item is not None:
            count += 1
    return count


def _client_backend_name() -> str:
    return (
        os.environ.get("SOURCE_SIM_OPCUA_CLIENT_BACKEND")
        or os.environ.get("WHALE_OPCUA_CLIENT_BACKEND")
        or "asyncua"
    )


LOAD_LEVEL_DURATION_S = _env_float("SOURCE_SIM_LOAD_LEVEL_DURATION_S", 30.0)
WARMUP_S = _env_float("SOURCE_SIM_LOAD_WARMUP_S", 3.0)
READ_TIMEOUT_S = _env_float("SOURCE_SIM_LOAD_READ_TIMEOUT_S", 5.0)

SERVER_COUNT_START = _env_first_int(
    ("SOURCE_SIM_LOAD_SERVER_COUNT", "SOURCE_SIM_LOAD_SERVER_COUNT_START"), 9
)
SERVER_COUNT_STEP = _env_int("SOURCE_SIM_LOAD_SERVER_COUNT_STEP", 1)
SERVER_COUNT_MAX = _env_first_int(
    ("SOURCE_SIM_LOAD_SERVER_COUNT", "SOURCE_SIM_LOAD_SERVER_COUNT_MAX"),
    SERVER_COUNT_START,
)

HZ_START = _env_first_float(("SOURCE_SIM_LOAD_TARGET_HZ", "SOURCE_SIM_LOAD_HZ_START"), 9.0)
HZ_STEP = _env_float("SOURCE_SIM_LOAD_HZ_STEP", 1.0)
HZ_MAX = _env_first_float(("SOURCE_SIM_LOAD_TARGET_HZ", "SOURCE_SIM_LOAD_HZ_MAX"), HZ_START)

MAX_CONCURRENT_READS = _env_first_int(
    (
        "SOURCE_SIM_LOAD_MAX_CONCURRENT_READS",
        "SOURCE_SIM_LOAD_MAX_CONCURRENT_READS_PER_WORKER",
    ),
    16,
)

MIN_EXPECTED_POINT_COUNT = _env_int("SOURCE_SIM_LOAD_MIN_POINTS", 300)
MAX_EXPECTED_POINT_COUNT = _env_int("SOURCE_SIM_LOAD_MAX_POINTS", 500)
SOURCE_UPDATE_HZ = _env_float("SOURCE_SIM_LOAD_SOURCE_UPDATE_HZ", 10.0)
SOURCE_UPDATE_ENABLED = _env_flag("SOURCE_SIM_LOAD_SOURCE_UPDATE_ENABLED", False)
PROCESS_COUNT = _env_int("SOURCE_SIM_LOAD_PROCESS_COUNT", 1)
COROUTINES_PER_PROCESS = _env_int("SOURCE_SIM_LOAD_COROUTINES_PER_PROCESS", 0)
PERIOD_MAX_TOLERANCE_RATIO = _env_first_float(
    (
        "SOURCE_SIM_LOAD_PERIOD_MAX_TOLERANCE_RATIO",
        "SOURCE_SIM_LOAD_PERIOD_TOLERANCE_RATIO",
    ),
    0.2,
)
PERIOD_MEAN_ERROR_RATIO = _env_float("SOURCE_SIM_LOAD_PERIOD_MEAN_ERROR_RATIO", 0.05)
FAIL_CONFIRM_RUNS = _env_int("SOURCE_SIM_LOAD_FAIL_CONFIRM_RUNS", 2)
TOP_GAP_COUNT = _env_int("SOURCE_SIM_LOAD_TOP_GAP_COUNT", 5)
ACCEPT_FLAKY_AS_PASS = _env_flag("SOURCE_SIM_LOAD_ACCEPT_FLAKY_AS_PASS", False)
STOP_SERVER_RAMP_ON_FIRST_FAIL = _env_flag("SOURCE_SIM_LOAD_STOP_SERVER_RAMP_ON_FIRST_FAIL", True)
FLEET_STOP_GRACE_S = _env_float("SOURCE_SIM_FLEET_STOP_GRACE_S", 0.2)
VERBOSE_ERRORS = _env_flag("SOURCE_SIM_LOAD_VERBOSE_ERRORS", False)


@dataclass(slots=True)
class TickResult:
    ok: bool
    value_count: int
    elapsed_ms: float
    response_timestamp_s: float | None
    error: str | None = None


@dataclass(slots=True)
class ReaderStats:
    total_reads: int = 0
    ok_reads: int = 0
    read_errors: int = 0
    batch_mismatches: int = 0
    missing_response_timestamps: int = 0
    tick_ms_values: list[float] = field(default_factory=list)
    response_timestamps: list[float] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class PeriodGap:
    reader_index: int
    gap_index: int
    previous_timestamp_s: float
    current_timestamp_s: float
    period_ms: float


@dataclass(frozen=True, slots=True)
class LevelMetrics:
    server_count: int
    target_hz: float
    target_period_ms: float
    allowed_period_max_ms: float
    allowed_period_mean_abs_error_ms: float
    read_errors: int
    batch_mismatches: int
    missing_response_timestamps: int
    period_samples: int
    period_mean_ms: float
    period_max_ms: float
    period_mean_abs_error_ms: float
    max_observed_concurrent_reads: int
    value_count_ok: bool
    period_max_ok: bool
    period_mean_ok: bool
    passed: bool
    failure_reason: str
    worst_gap: PeriodGap | None
    top_gaps: tuple[PeriodGap, ...]


@dataclass(frozen=True, slots=True)
class ResponsePeriodStats:
    samples: int
    mean_ms: float
    max_ms: float
    mean_abs_error_ms: float
    worst_gap: PeriodGap | None
    top_gaps: tuple[PeriodGap, ...]


@dataclass(frozen=True, slots=True)
class SourceReadSpec:
    global_index: int
    source: SimulatedSource
    offset_seconds: float


@dataclass(frozen=True, slots=True)
class WorkerRawStats:
    worker_index: int
    reader_count: int
    batch_mismatches: int
    read_errors: int
    missing_response_timestamps: int
    response_timestamps_by_reader: tuple[tuple[float, ...], ...]
    max_observed_concurrent_reads: int


@dataclass(frozen=True, slots=True)
class ConfirmedLevelResult:
    primary: LevelMetrics
    attempts: tuple[LevelMetrics, ...]
    final_status: str
    final_reason: str


class OpcUaLoadReader:
    def __init__(self, source: SimulatedSource) -> None:
        self._source = source
        self._reader: OpcUaSourceReader | None = None
        self._plan: PreparedReadPlan | None = None
        self._addresses = tuple(f"s={logical_path(source.connection, point)}" for point in source.points)

    async def connect(self) -> None:
        self._reader = OpcUaSourceReader(
            SourceConnectionProfile(
                endpoint=build_opcua_endpoint(self._source.connection),
                namespace_uri=self._source.connection.namespace_uri,
                timeout_seconds=READ_TIMEOUT_S,
            )
        )
        await self._reader.__aenter__()
        self._plan = self._reader.prepare_read(self._addresses)

    async def close(self) -> None:
        if self._reader is None:
            return
        try:
            await self._reader.__aexit__(None, None, None)
        finally:
            self._reader = None
            self._plan = None

    async def read_tick(self, *, expected_value_count: int) -> TickResult:
        if self._reader is None or self._plan is None:
            return TickResult(False, 0, 0.0, None, "reader_not_connected")

        started_at = time.perf_counter()
        try:
            raw = await self._reader.read_prepared_raw(self._plan)
        except Exception as exc:
            elapsed_ms = (time.perf_counter() - started_at) * 1000.0
            return TickResult(False, 0, elapsed_ms, None, type(exc).__name__)

        elapsed_ms = (time.perf_counter() - started_at) * 1000.0
        value_count = _raw_value_count(raw.data_values)
        response_timestamp_s = (
            raw.response_timestamp.timestamp() if isinstance(raw.response_timestamp, datetime) else None
        )

        if not raw.ok:
            return TickResult(False, value_count, elapsed_ms, response_timestamp_s, raw.error_reason)
        if value_count != expected_value_count:
            return TickResult(False, value_count, elapsed_ms, response_timestamp_s, "batch_mismatch")
        if response_timestamp_s is None:
            return TickResult(False, value_count, elapsed_ms, None, "missing_response_timestamp")
        return TickResult(True, value_count, elapsed_ms, response_timestamp_s)


async def _run_bounded(
    readers: Sequence[OpcUaLoadReader],
    action: Callable[[OpcUaLoadReader], Awaitable[object]],
) -> None:
    semaphore = asyncio.Semaphore(max(1, min(MAX_CONCURRENT_READS, 8)))

    async def run_one(reader: OpcUaLoadReader) -> None:
        async with semaphore:
            await asyncio.wait_for(action(reader), timeout=max(READ_TIMEOUT_S, 10.0))

    await asyncio.gather(*(run_one(reader) for reader in readers))


async def _run_worker_level(
    specs: Sequence[SourceReadSpec],
    *,
    target_hz: float,
    worker_index: int,
) -> WorkerRawStats:
    readers = tuple(OpcUaLoadReader(spec.source) for spec in specs)
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

    limiter = ReadConcurrencyLimiter[TickResult](max_concurrent=MAX_CONCURRENT_READS)
    scheduler = SourcePollingScheduler[TickResult](limiter=limiter, diagnostics_enabled=False)
    loop = asyncio.get_running_loop()
    measure_start_at = loop.time() + WARMUP_S
    measure_end_at = measure_start_at + LOAD_LEVEL_DURATION_S

    def make_result_handler(reader_index: int):
        async def on_result(event: PollingResultEvent[TickResult]) -> None:
            if measure_start_at <= event.finished_at <= measure_end_at:
                _record_tick(reader_stats[reader_index], event.result)
        return on_result

    def make_error_handler(reader_index: int):
        async def on_error(event: PollingErrorEvent) -> None:
            if measure_start_at <= event.finished_at <= measure_end_at:
                _record_tick(
                    reader_stats[reader_index],
                    TickResult(False, 0, event.duration_ms, None, event.error_type),
                )
        return on_error

    await _run_bounded(readers, lambda reader: reader.connect())
    try:
        for index, (reader, spec) in enumerate(zip(readers, specs)):
            scheduler.add_job(
                PollingJobSpec[TickResult](
                    job_id=f"opcua-reader-{spec.global_index}",
                    interval_seconds=interval_seconds,
                    offset_seconds=spec.offset_seconds,
                    timeout_seconds=READ_TIMEOUT_S,
                    operation=lambda reader=reader: reader.read_tick(
                        expected_value_count=expected_value_count
                    ),
                    on_result=make_result_handler(index),
                    on_error=make_error_handler(index),
                )
            )
        await scheduler.start()
        try:
            await asyncio.sleep(WARMUP_S + LOAD_LEVEL_DURATION_S)
        finally:
            await scheduler.stop()
    finally:
        await _run_bounded(readers, lambda reader: reader.close())

    concurrency = await limiter.snapshot()
    return WorkerRawStats(
        worker_index=worker_index,
        reader_count=len(readers),
        batch_mismatches=sum(item.batch_mismatches for item in reader_stats),
        read_errors=sum(item.read_errors for item in reader_stats),
        missing_response_timestamps=sum(
            item.missing_response_timestamps for item in reader_stats
        ),
        response_timestamps_by_reader=tuple(
            tuple(item.response_timestamps) for item in reader_stats
        ),
        max_observed_concurrent_reads=concurrency.max_observed_active,
    )


def _run_worker_entry(
    worker_index: int,
    specs: tuple[SourceReadSpec, ...],
    target_hz: float,
) -> WorkerRawStats:
    return asyncio.run(
        _run_worker_level(specs, target_hz=target_hz, worker_index=worker_index)
    )


def _record_tick(stats: ReaderStats, result: TickResult) -> None:
    stats.total_reads += 1
    stats.tick_ms_values.append(result.elapsed_ms)
    if result.error == "batch_mismatch":
        stats.batch_mismatches += 1
        return
    if result.error == "missing_response_timestamp":
        stats.missing_response_timestamps += 1
        return
    if not result.ok:
        stats.read_errors += 1
        return
    stats.ok_reads += 1
    if result.response_timestamp_s is not None:
        stats.response_timestamps.append(result.response_timestamp_s)


def evaluate_response_periods(
    response_timestamps_by_reader: Sequence[Sequence[float]],
    *,
    target_period_ms: float,
    top_n: int = 5,
) -> ResponsePeriodStats:
    """Return aggregate adjacent response-timestamp period statistics."""

    gaps: list[PeriodGap] = []
    for reader_index, timestamps in enumerate(response_timestamps_by_reader):
        ordered = sorted(timestamps)
        for gap_index, (previous, current) in enumerate(zip(ordered, ordered[1:])):
            delta_ms = (current - previous) * 1000.0
            if delta_ms >= 0:
                gaps.append(
                    PeriodGap(
                        reader_index=reader_index,
                        gap_index=gap_index,
                        previous_timestamp_s=previous,
                        current_timestamp_s=current,
                        period_ms=delta_ms,
                    )
                )

    if not gaps:
        return ResponsePeriodStats(
            samples=0,
            mean_ms=0.0,
            max_ms=0.0,
            mean_abs_error_ms=0.0,
            worst_gap=None,
            top_gaps=(),
        )

    values = [gap.period_ms for gap in gaps]
    mean_ms = sum(values) / len(values)
    top_gaps = tuple(
        sorted(gaps, key=lambda gap: gap.period_ms, reverse=True)[:top_n]
    )
    return ResponsePeriodStats(
        samples=len(values),
        mean_ms=mean_ms,
        max_ms=max(values),
        mean_abs_error_ms=abs(mean_ms - target_period_ms),
        worst_gap=top_gaps[0] if top_gaps else None,
        top_gaps=top_gaps,
    )


def _build_metrics(
    worker_stats: Sequence[WorkerRawStats],
    *,
    server_count: int,
    target_hz: float,
) -> LevelMetrics:
    read_errors = sum(item.read_errors for item in worker_stats)
    batch_mismatches = sum(item.batch_mismatches for item in worker_stats)
    missing_response_timestamps = sum(
        item.missing_response_timestamps for item in worker_stats
    )
    response_timestamps_by_reader = tuple(
        timestamps
        for worker in worker_stats
        for timestamps in worker.response_timestamps_by_reader
    )
    max_observed_concurrent_reads = sum(
        item.max_observed_concurrent_reads for item in worker_stats
    )
    target_period_ms = 1000.0 / target_hz
    period_stats = evaluate_response_periods(
        response_timestamps_by_reader,
        target_period_ms=target_period_ms,
        top_n=TOP_GAP_COUNT,
    )
    allowed_period_max_ms = target_period_ms * (1.0 + PERIOD_MAX_TOLERANCE_RATIO)
    allowed_period_mean_abs_error_ms = target_period_ms * PERIOD_MEAN_ERROR_RATIO
    value_count_ok = batch_mismatches == 0
    period_max_ok = (
        period_stats.samples > 0 and period_stats.max_ms <= allowed_period_max_ms
    )
    period_mean_ok = (
        period_stats.samples > 0
        and period_stats.mean_abs_error_ms <= allowed_period_mean_abs_error_ms
    )

    reasons: list[str] = []
    if not value_count_ok:
        reasons.append(f"bad={batch_mismatches}")
    if period_stats.samples <= 0:
        reasons.append("p_n=0")
    else:
        if not period_max_ok:
            reasons.append(f"pmax={period_stats.max_ms:.1f}>{allowed_period_max_ms:.1f}")
        if not period_mean_ok:
            reasons.append(
                f"mean_err={period_stats.mean_abs_error_ms:.2f}>"
                f"{allowed_period_mean_abs_error_ms:.2f}"
            )

    failure_reason = "; ".join(reasons)
    return LevelMetrics(
        server_count=server_count,
        target_hz=target_hz,
        target_period_ms=round(target_period_ms, 1),
        allowed_period_max_ms=round(allowed_period_max_ms, 1),
        allowed_period_mean_abs_error_ms=round(allowed_period_mean_abs_error_ms, 2),
        read_errors=read_errors,
        batch_mismatches=batch_mismatches,
        missing_response_timestamps=missing_response_timestamps,
        period_samples=period_stats.samples,
        period_mean_ms=round(period_stats.mean_ms, 2),
        period_max_ms=round(period_stats.max_ms, 1),
        period_mean_abs_error_ms=round(period_stats.mean_abs_error_ms, 2),
        max_observed_concurrent_reads=max_observed_concurrent_reads,
        value_count_ok=value_count_ok,
        period_max_ok=period_max_ok,
        period_mean_ok=period_mean_ok,
        passed=value_count_ok and period_max_ok and period_mean_ok,
        failure_reason=failure_reason,
        worst_gap=period_stats.worst_gap,
        top_gaps=period_stats.top_gaps,
    )


def _build_source_specs(
    sources: Sequence[SimulatedSource],
    *,
    target_hz: float,
) -> tuple[SourceReadSpec, ...]:
    offsets = build_even_stagger_offsets(
        count=len(sources),
        interval_seconds=1.0 / target_hz,
    )
    return tuple(
        SourceReadSpec(global_index=index, source=source, offset_seconds=offsets[index])
        for index, source in enumerate(sources)
    )


def _partition_specs_round_robin(
    specs: Sequence[SourceReadSpec],
    *,
    process_count: int,
) -> tuple[tuple[SourceReadSpec, ...], ...]:
    buckets: list[list[SourceReadSpec]] = [[] for _ in range(process_count)]
    for index, spec in enumerate(specs):
        buckets[index % process_count].append(spec)
    return tuple(tuple(bucket) for bucket in buckets)


def _mp_context() -> mp.context.BaseContext:
    methods = mp.get_all_start_methods()
    if "fork" in methods:
        return mp.get_context("fork")
    return mp.get_context()


def _run_level_once(
    sources: Sequence[SimulatedSource],
    *,
    target_hz: float,
) -> LevelMetrics:
    specs = _build_source_specs(sources, target_hz=target_hz)
    partitions = _partition_specs_round_robin(specs, process_count=PROCESS_COUNT)
    if PROCESS_COUNT == 1:
        worker_stats = (
            asyncio.run(
                _run_worker_level(partitions[0], target_hz=target_hz, worker_index=0)
            ),
        )
    else:
        with ProcessPoolExecutor(
            max_workers=PROCESS_COUNT,
            mp_context=_mp_context(),
        ) as executor:
            futures = [
                executor.submit(_run_worker_entry, index, bucket, target_hz)
                for index, bucket in enumerate(partitions)
                if bucket
            ]
            worker_stats = tuple(future.result() for future in futures)
    return _build_metrics(worker_stats, server_count=len(sources), target_hz=target_hz)


def _build_skip_result(
    *,
    server_count: int,
    target_hz: float,
    reason: str,
) -> ConfirmedLevelResult:
    target_period_ms = 1000.0 / target_hz
    metrics = LevelMetrics(
        server_count=server_count,
        target_hz=target_hz,
        target_period_ms=round(target_period_ms, 1),
        allowed_period_max_ms=round(
            target_period_ms * (1.0 + PERIOD_MAX_TOLERANCE_RATIO), 1
        ),
        allowed_period_mean_abs_error_ms=round(
            target_period_ms * PERIOD_MEAN_ERROR_RATIO, 2
        ),
        read_errors=0,
        batch_mismatches=0,
        missing_response_timestamps=0,
        period_samples=0,
        period_mean_ms=0.0,
        period_max_ms=0.0,
        period_mean_abs_error_ms=0.0,
        max_observed_concurrent_reads=0,
        value_count_ok=True,
        period_max_ok=False,
        period_mean_ok=False,
        passed=False,
        failure_reason=reason,
        worst_gap=None,
        top_gaps=(),
    )
    return ConfirmedLevelResult(
        primary=metrics,
        attempts=(metrics,),
        final_status="SKIP",
        final_reason=reason,
    )


def _run_confirmed_level(
    sources: Sequence[SimulatedSource],
    *,
    target_hz: float,
) -> ConfirmedLevelResult:
    if (
        COROUTINES_PER_PROCESS > 0
        and len(sources) > PROCESS_COUNT * COROUTINES_PER_PROCESS
    ):
        return _build_skip_result(
            server_count=len(sources),
            target_hz=target_hz,
            reason="server_count exceeds process_count * coroutines_per_process",
        )

    attempts: list[LevelMetrics] = []
    max_attempts = max(1, FAIL_CONFIRM_RUNS)
    for _ in range(max_attempts):
        metrics = _run_level_once(sources, target_hz=target_hz)
        attempts.append(metrics)
        if metrics.passed:
            if len(attempts) == 1:
                return ConfirmedLevelResult(
                    primary=attempts[0],
                    attempts=tuple(attempts),
                    final_status="PASS",
                    final_reason="",
                )
            return ConfirmedLevelResult(
                primary=attempts[0],
                attempts=tuple(attempts),
                final_status="FLAKY",
                final_reason=f"recovered on attempt {len(attempts)}",
            )

    return ConfirmedLevelResult(
        primary=attempts[0],
        attempts=tuple(attempts),
        final_status="FAIL",
        final_reason=attempts[-1].failure_reason,
    )


@contextmanager
def _started_fleet(sources: tuple[SimulatedSource, ...]):
    vars_per_server = len(sources[0].points)
    update_interval_s = 1.0 / SOURCE_UPDATE_HZ if SOURCE_UPDATE_HZ > 0 else 1.0
    fleet = SourceSimulatorFleet.create(
        sources=sources,
        update_config=UpdateConfig(
            enabled=SOURCE_UPDATE_ENABLED,
            interval_seconds=update_interval_s,
            update_count=vars_per_server,
        ),
    )
    try:
        with fleet:
            yield
    finally:
        if FLEET_STOP_GRACE_S > 0:
            time.sleep(FLEET_STOP_GRACE_S)


def _print_header() -> None:
    print()
    print("=" * 116)
    print("OPC UA multi-server capacity scan")
    print("=" * 116)
    print(f"backend={os.environ.get('SOURCE_SIM_OPCUA_BACKEND', 'asyncua')}")
    print(f"client_backend={_client_backend_name()}")
    print("reader_mode=raw_prepared")
    print("read_schedule=global_stagger")
    print(f"server_count={SERVER_COUNT_START}:{SERVER_COUNT_STEP}:{SERVER_COUNT_MAX}")
    print(f"hz={HZ_START}:{HZ_STEP}:{HZ_MAX}")
    print(f"duration={LOAD_LEVEL_DURATION_S:.1f}s warmup={WARMUP_S:.1f}s")
    print(f"source_update_enabled={SOURCE_UPDATE_ENABLED} source_update_hz={SOURCE_UPDATE_HZ:.1f}")
    print(f"process_count={PROCESS_COUNT}")
    print(f"coroutines_per_process={COROUTINES_PER_PROCESS}")
    port_allocator = PortAllocator.from_env()
    print(f"port_range={port_allocator.start}:{port_allocator.end}")
    print(f"max_concurrent_reads={MAX_CONCURRENT_READS}")
    print(f"period_max_tol={PERIOD_MAX_TOLERANCE_RATIO:.0%}")
    print(f"period_mean_error_tol={PERIOD_MEAN_ERROR_RATIO:.0%}")
    print(f"fail_confirm_runs={FAIL_CONFIRM_RUNS}")
    print(f"top_gap_count={TOP_GAP_COUNT}")
    print(f"accept_flaky_as_pass={ACCEPT_FLAKY_AS_PASS}")
    print("-" * 116)
    print(
        f"{'srv':>4} {'hz':>6} {'period':>8} {'bad':>5} "
        f"{'p_n':>7} {'p_mean':>8} {'p_max':>7} {'mean_err':>9} "
        f"{'conc':>5} {'status':>7} reason"
    )
    print("-" * 116)


def _print_level(result: ConfirmedLevelResult) -> None:
    metrics = result.primary
    print(
        f"{metrics.server_count:>4} {metrics.target_hz:>6.1f} "
        f"{metrics.target_period_ms:>8.1f} "
        f"{metrics.batch_mismatches:>5} {metrics.period_samples:>7} "
        f"{metrics.period_mean_ms:>8.2f} {metrics.period_max_ms:>7.1f} "
        f"{metrics.period_mean_abs_error_ms:>9.2f} "
        f"{metrics.max_observed_concurrent_reads:>5} "
        f"{result.final_status:>7} {result.final_reason or metrics.failure_reason}"
    )


def _representative_metrics(result: ConfirmedLevelResult) -> LevelMetrics:
    return max(
        result.attempts,
        key=lambda item: (item.period_max_ms, item.period_mean_abs_error_ms),
    )


def _print_top_gaps(result: ConfirmedLevelResult) -> None:
    if result.final_status not in {"FAIL", "FLAKY"}:
        return
    metrics = _representative_metrics(result)
    if not metrics.top_gaps:
        return
    print("  top response period gaps:")
    print("    reader  gap    period_ms    prev_ts             cur_ts")
    for gap in metrics.top_gaps:
        print(
            f"    {gap.reader_index:>6} {gap.gap_index:>4} "
            f"{gap.period_ms:>12.1f} {gap.previous_timestamp_s:>17.3f} "
            f"{gap.current_timestamp_s:>17.3f}"
        )


def _summarize_fleet_start_exception(exc: Exception) -> str:
    lines = [line.strip() for line in str(exc).splitlines() if line.strip()]
    if not lines:
        return type(exc).__name__

    summary = lines[0]
    for line in lines[1:]:
        if "endpoint=" in line:
            summary = line
            break

    if "Address already in use" in str(exc) and "Address already in use" not in summary:
        summary = f"{summary}; Address already in use"

    return summary


def _print_summary(results: Sequence[ConfirmedLevelResult]) -> None:
    print("-" * 116)
    print("max pass by server_count:")
    for server_count in _iter_int_ramp(SERVER_COUNT_START, SERVER_COUNT_STEP, SERVER_COUNT_MAX):
        levels = [item for item in results if item.primary.server_count == server_count]
        if not levels:
            continue
        accepted_statuses = {"PASS"}
        if ACCEPT_FLAKY_AS_PASS:
            accepted_statuses.add("FLAKY")
        accepted = [item for item in levels if item.final_status in accepted_statuses]
        flaky = [item for item in levels if item.final_status == "FLAKY"]
        if not accepted:
            extra = ""
            if flaky:
                extra = f", flaky_hz={flaky[-1].primary.target_hz:.1f}"
            print(f"  srv={server_count}: N/A{extra}")
            continue
        best = accepted[-1].primary
        suffix = " (flaky)" if levels[-1].final_status == "FLAKY" and ACCEPT_FLAKY_AS_PASS else ""
        print(
            f"  srv={server_count}: max_hz={best.target_hz:.1f}, "
            f"p_max={best.period_max_ms:.1f}ms, "
            f"mean_err={best.period_mean_abs_error_ms:.2f}ms, "
            f"conc={best.max_observed_concurrent_reads}{suffix}"
        )
    print("=" * 116)


@pytest.mark.load
def test_source_simulation_multi_server_capacity() -> None:
    if SERVER_COUNT_START <= 0 or SERVER_COUNT_STEP <= 0 or SERVER_COUNT_MAX < SERVER_COUNT_START:
        raise ValueError("invalid server-count ramp settings")
    if HZ_START <= 0 or HZ_STEP <= 0 or HZ_MAX < HZ_START:
        raise ValueError("invalid Hz ramp settings")
    if MAX_CONCURRENT_READS <= 0:
        raise ValueError("SOURCE_SIM_LOAD_MAX_CONCURRENT_READS must be greater than 0")

    base_source = build_opcua_source_from_repository(
        min_expected_point_count=MIN_EXPECTED_POINT_COUNT,
        max_expected_point_count=MAX_EXPECTED_POINT_COUNT,
    )
    port_allocator = PortAllocator.from_env()

    _print_header()
    all_results: list[ConfirmedLevelResult] = []

    for server_count in _iter_int_ramp(SERVER_COUNT_START, SERVER_COUNT_STEP, SERVER_COUNT_MAX):
        ports = port_allocator.allocate_many(
            server_count,
            host=base_source.connection.host,
        )
        sources = build_multi_sources(base_source, server_count=server_count, ports=ports)
        server_has_accepted = False
        try:
            with _started_fleet(sources):
                for target_hz in _iter_float_ramp(HZ_START, HZ_STEP, HZ_MAX):
                    result = _run_confirmed_level(sources, target_hz=target_hz)
                    all_results.append(result)
                    _print_level(result)
                    _print_top_gaps(result)
                    if result.final_status == "PASS" or (
                        ACCEPT_FLAKY_AS_PASS and result.final_status == "FLAKY"
                    ):
                        server_has_accepted = True
                        continue
                    if result.final_status == "FLAKY":
                        continue
                    if result.final_status in {"FAIL", "SKIP"}:
                        break
        except Exception as exc:
            port_span = f"{ports[0]}-{ports[-1]}" if ports else "n/a"
            summary = _summarize_fleet_start_exception(exc)
            result = _build_skip_result(
                server_count=server_count,
                target_hz=HZ_START,
                reason=f"fleet_start_failed: {summary}; ports={port_span}",
            )
            all_results.append(result)
            _print_level(result)
            if VERBOSE_ERRORS:
                print(exc)
        if STOP_SERVER_RAMP_ON_FIRST_FAIL and not server_has_accepted:
            break

    _print_summary(all_results)
    assert all_results, "No capacity level was executed"
    assert any(
        item.final_status == "PASS"
        or (ACCEPT_FLAKY_AS_PASS and item.final_status == "FLAKY")
        for item in all_results
    ), "No capacity level passed"
