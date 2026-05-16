"""Profile one multi-server OPC UA polling level with pyinstrument.

Purpose:
- Run one specific server_count + sampling-rate configuration.
- Print final load metrics, compact diagnosis, top response-period gaps, and a bounded
  pyinstrument call tree directly to stdout.
- Use this after the capacity test identifies a near-limit or failing level.

This profile intentionally supports only one Python process. Multi-process profiling is
not implemented here because pyinstrument output would only describe the parent process
unless worker profiling is explicitly wired.

Install dependency:
    pip install pyinstrument

Typical run:
    SOURCE_SIM_OPCUA_BACKEND=open62541 \
    SOURCE_SIM_OPCUA_CLIENT_BACKEND=open62541 \
    SOURCE_SIM_LOAD_PROCESS_COUNT=1 \
    SOURCE_SIM_LOAD_COROUTINES_PER_PROCESS=0 \
    SOURCE_SIM_LOAD_SERVER_COUNT=10 \
    SOURCE_SIM_LOAD_TARGET_HZ=10 \
    SOURCE_SIM_LOAD_LEVEL_DURATION_S=30 \
    SOURCE_SIM_LOAD_WARMUP_S=10 \
    SOURCE_SIM_LOAD_SOURCE_UPDATE_ENABLED=false \
    SOURCE_SIM_LOAD_MAX_CONCURRENT_READS=16 \
    SOURCE_SIM_PROFILE_SHOW_ALL=false \
    SOURCE_SIM_PROFILE_MAX_LINES=80 \
    python -m pytest tools/source_lab/tests/test_source_simulation_multi_server_profile.py -s -v
"""

from __future__ import annotations

import asyncio
import os
import re
import time
from collections.abc import Awaitable, Callable, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

import pytest

try:
    from pyinstrument import Profiler
except ImportError:  # pragma: no cover - optional dependency
    Profiler = None  # type: ignore[assignment]

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


def _optional_gap_ms(current: int | None, previous: int | None) -> float | None:
    if current is None or previous is None:
        return None
    return (current - previous) / 1_000_000.0


def _optional_duration_ms(end: int | None, start: int | None) -> float | None:
    if end is None or start is None:
        return None
    return max(0.0, (end - start) / 1_000_000.0)


def _format_optional_ms(value: float | None, *, width: int = 13) -> str:
    if value is None:
        return f"{'-':>{width}}"
    return f"{value:>{width}.1f}"


def _debug_timing_kwargs(debug_timing: object | None) -> dict[str, int | None]:
    return {
        "command_write_ts_ns": getattr(debug_timing, "command_write_ts_ns", None),
        "command_drain_done_ts_ns": getattr(debug_timing, "command_drain_done_ts_ns", None),
        "stdout_line_received_ts_ns": getattr(debug_timing, "stdout_line_received_ts_ns", None),
        "runner_request_received_ts_ns": getattr(debug_timing, "runner_request_received_ts_ns", None),
        "runner_read_start_ts_ns": getattr(debug_timing, "runner_read_start_ts_ns", None),
        "runner_read_end_ts_ns": getattr(debug_timing, "runner_read_end_ts_ns", None),
        "runner_response_write_ts_ns": getattr(debug_timing, "runner_response_write_ts_ns", None),
    }


def _client_backend_name() -> str:
    return (
        os.environ.get("SOURCE_SIM_OPCUA_CLIENT_BACKEND")
        or os.environ.get("WHALE_OPCUA_CLIENT_BACKEND")
        or "asyncua"
    )


LOAD_LEVEL_DURATION_S = _env_float("SOURCE_SIM_LOAD_LEVEL_DURATION_S", 30.0)
WARMUP_S = _env_float("SOURCE_SIM_LOAD_WARMUP_S", 3.0)
READ_TIMEOUT_S = _env_float("SOURCE_SIM_LOAD_READ_TIMEOUT_S", 5.0)
PROCESS_COUNT = _env_int("SOURCE_SIM_LOAD_PROCESS_COUNT", 1)
COROUTINES_PER_PROCESS = _env_int("SOURCE_SIM_LOAD_COROUTINES_PER_PROCESS", 0)
SERVER_COUNT = _env_first_int(("SOURCE_SIM_LOAD_SERVER_COUNT", "SOURCE_SIM_LOAD_SERVER_COUNT_START"), 9)
TARGET_HZ = _env_first_float(("SOURCE_SIM_LOAD_TARGET_HZ", "SOURCE_SIM_LOAD_HZ_START"), 9.0)
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
PERIOD_MAX_TOLERANCE_RATIO = _env_first_float(
    (
        "SOURCE_SIM_LOAD_PERIOD_MAX_TOLERANCE_RATIO",
        "SOURCE_SIM_LOAD_PERIOD_TOLERANCE_RATIO",
    ),
    0.2,
)
PERIOD_MEAN_ERROR_RATIO = _env_float("SOURCE_SIM_LOAD_PERIOD_MEAN_ERROR_RATIO", 0.05)
TOP_GAP_COUNT = _env_int("SOURCE_SIM_LOAD_TOP_GAP_COUNT", 5)
SHOW_ALL_FRAMES = _env_flag("SOURCE_SIM_PROFILE_SHOW_ALL", False)
PROFILE_MAX_LINES = _env_int("SOURCE_SIM_PROFILE_MAX_LINES", 80)


@dataclass(slots=True)
class TickResult:
    ok: bool
    value_count: int
    elapsed_ms: float
    response_timestamp_s: float | None
    read_start_monotonic: float
    read_finish_monotonic: float
    error: str | None = None
    command_write_ts_ns: int | None = None
    command_drain_done_ts_ns: int | None = None
    stdout_line_received_ts_ns: int | None = None
    runner_request_received_ts_ns: int | None = None
    runner_read_start_ts_ns: int | None = None
    runner_read_end_ts_ns: int | None = None
    runner_response_write_ts_ns: int | None = None


@dataclass(frozen=True, slots=True)
class TickSample:
    reader_index: int
    tick_index: int
    read_start_monotonic: float
    read_finish_monotonic: float
    response_timestamp_s: float | None
    value_count: int | None
    error: str | None
    command_write_ts_ns: int | None = None
    command_drain_done_ts_ns: int | None = None
    stdout_line_received_ts_ns: int | None = None
    runner_request_received_ts_ns: int | None = None
    runner_read_start_ts_ns: int | None = None
    runner_read_end_ts_ns: int | None = None
    runner_response_write_ts_ns: int | None = None

    @property
    def read_ms(self) -> float:
        return max(0.0, (self.read_finish_monotonic - self.read_start_monotonic) * 1000.0)


@dataclass(slots=True)
class ReaderStats:
    total_reads: int = 0
    ok_reads: int = 0
    read_errors: int = 0
    batch_mismatches: int = 0
    missing_response_timestamps: int = 0
    tick_ms_values: list[float] = field(default_factory=list)
    tick_samples: list[TickSample] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class PeriodGap:
    reader_index: int
    gap_index: int
    previous_timestamp_s: float
    current_timestamp_s: float
    period_ms: float
    previous_finish_monotonic: float
    current_finish_monotonic: float
    finish_gap_ms: float
    previous_read_ms: float
    current_read_ms: float
    py_cmd_gap_ms: float | None = None
    py_stdout_gap_ms: float | None = None
    runner_req_gap_ms: float | None = None
    runner_read_ms: float | None = None
    runner_write_gap_ms: float | None = None
    pipe_back_ms: float | None = None


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
class ProfileSummary:
    duration_s: float | None
    cpu_time_s: float | None
    text: str


@dataclass(frozen=True, slots=True)
class Diagnosis:
    not_python_cpu_bound: bool
    python_cpu_bound: bool
    asyncua_binary_codec_hotspot: bool
    slow_read_tick: bool
    scheduler_or_external_timestamp_jitter: bool
    cpu_ratio: float | None
    max_top_gap_cur_read_ms: float
    conclusion: str


class OpcUaProfileReader:
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

    def _last_open62541_debug_timing(self) -> object | None:
        if self._reader is None:
            return None
        backend = getattr(self._reader, "_backend", None)
        if backend is None:
            backend = getattr(self._reader, "_client_backend", None)
        if backend is None:
            backend = getattr(self._reader, "backend", None)
        return getattr(backend, "last_read_debug_timing", None)

    async def read_tick(self, *, expected_value_count: int) -> TickResult:
        read_start_monotonic = time.perf_counter()
        if self._reader is None or self._plan is None:
            read_finish_monotonic = time.perf_counter()
            return TickResult(
                False,
                0,
                (read_finish_monotonic - read_start_monotonic) * 1000.0,
                None,
                read_start_monotonic,
                read_finish_monotonic,
                "reader_not_connected",
            )

        try:
            raw = await self._reader.read_prepared_raw(self._plan)
        except Exception as exc:
            read_finish_monotonic = time.perf_counter()
            return TickResult(
                False,
                0,
                (read_finish_monotonic - read_start_monotonic) * 1000.0,
                None,
                read_start_monotonic,
                read_finish_monotonic,
                type(exc).__name__,
            )

        debug_timing = self._last_open62541_debug_timing()
        read_finish_monotonic = time.perf_counter()
        elapsed_ms = (read_finish_monotonic - read_start_monotonic) * 1000.0
        value_count = _raw_value_count(raw.data_values)
        response_timestamp_s = (
            raw.response_timestamp.timestamp() if isinstance(raw.response_timestamp, datetime) else None
        )
        if not raw.ok:
            return TickResult(
                False,
                value_count,
                elapsed_ms,
                response_timestamp_s,
                read_start_monotonic,
                read_finish_monotonic,
                raw.error_reason,
                **_debug_timing_kwargs(debug_timing),
            )
        if value_count != expected_value_count:
            return TickResult(
                False,
                value_count,
                elapsed_ms,
                response_timestamp_s,
                read_start_monotonic,
                read_finish_monotonic,
                "batch_mismatch",
                **_debug_timing_kwargs(debug_timing),
            )
        if response_timestamp_s is None:
            return TickResult(
                False,
                value_count,
                elapsed_ms,
                None,
                read_start_monotonic,
                read_finish_monotonic,
                "missing_response_timestamp",
                **_debug_timing_kwargs(debug_timing),
            )
        return TickResult(
            True,
            value_count,
            elapsed_ms,
            response_timestamp_s,
            read_start_monotonic,
            read_finish_monotonic,
            **_debug_timing_kwargs(debug_timing),
        )


async def _run_bounded(
    readers: Sequence[OpcUaProfileReader],
    action: Callable[[OpcUaProfileReader], Awaitable[object]],
) -> None:
    semaphore = asyncio.Semaphore(max(1, min(MAX_CONCURRENT_READS, 8)))

    async def run_one(reader: OpcUaProfileReader) -> None:
        async with semaphore:
            await asyncio.wait_for(action(reader), timeout=max(READ_TIMEOUT_S, 10.0))

    await asyncio.gather(*(run_one(reader) for reader in readers))


async def _run_profile_level(sources: Sequence[SimulatedSource]) -> LevelMetrics:
    readers = tuple(OpcUaProfileReader(source) for source in sources)
    reader_stats = [ReaderStats() for _ in readers]
    expected_value_count = len(sources[0].points)
    interval_seconds = 1.0 / TARGET_HZ
    offsets = build_even_stagger_offsets(count=len(readers), interval_seconds=interval_seconds)

    limiter = ReadConcurrencyLimiter[TickResult](max_concurrent=MAX_CONCURRENT_READS)
    scheduler = SourcePollingScheduler[TickResult](limiter=limiter, diagnostics_enabled=False)
    loop = asyncio.get_running_loop()
    measure_start_at = loop.time() + WARMUP_S
    measure_end_at = measure_start_at + LOAD_LEVEL_DURATION_S

    def make_result_handler(reader_index: int):
        async def on_result(event: PollingResultEvent[TickResult]) -> None:
            if measure_start_at <= event.finished_at <= measure_end_at:
                _record_tick(reader_stats[reader_index], event.result, reader_index=reader_index)

        return on_result

    def make_error_handler(reader_index: int):
        async def on_error(event: PollingErrorEvent) -> None:
            if measure_start_at <= event.finished_at <= measure_end_at:
                read_finish = time.perf_counter()
                read_start = read_finish - max(0.0, event.duration_ms / 1000.0)
                _record_tick(
                    reader_stats[reader_index],
                    TickResult(
                        False,
                        0,
                        event.duration_ms,
                        None,
                        read_start,
                        read_finish,
                        event.error_type,
                    ),
                    reader_index=reader_index,
                )

        return on_error

    await _run_bounded(readers, lambda reader: reader.connect())
    try:
        for index, reader in enumerate(readers):
            scheduler.add_job(
                PollingJobSpec[TickResult](
                    job_id=f"opcua-reader-{index}",
                    interval_seconds=interval_seconds,
                    offset_seconds=offsets[index],
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
    return _build_metrics(
        reader_stats,
        max_observed_concurrent_reads=concurrency.max_observed_active,
    )


def _record_tick(stats: ReaderStats, result: TickResult, *, reader_index: int) -> None:
    stats.total_reads += 1
    stats.tick_ms_values.append(result.elapsed_ms)
    stats.tick_samples.append(
        TickSample(
            reader_index=reader_index,
            tick_index=stats.total_reads - 1,
            read_start_monotonic=result.read_start_monotonic,
            read_finish_monotonic=result.read_finish_monotonic,
            response_timestamp_s=result.response_timestamp_s,
            value_count=result.value_count,
            error=result.error,
            command_write_ts_ns=result.command_write_ts_ns,
            command_drain_done_ts_ns=result.command_drain_done_ts_ns,
            stdout_line_received_ts_ns=result.stdout_line_received_ts_ns,
            runner_request_received_ts_ns=result.runner_request_received_ts_ns,
            runner_read_start_ts_ns=result.runner_read_start_ts_ns,
            runner_read_end_ts_ns=result.runner_read_end_ts_ns,
            runner_response_write_ts_ns=result.runner_response_write_ts_ns,
        )
    )

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


def evaluate_response_periods(
    tick_samples_by_reader: Sequence[Sequence[TickSample]],
    *,
    target_period_ms: float,
    top_n: int = 5,
) -> ResponsePeriodStats:
    """Return aggregate adjacent response-timestamp period statistics."""

    gaps: list[PeriodGap] = []
    for reader_index, samples in enumerate(tick_samples_by_reader):
        comparable_samples = [item for item in samples if item.response_timestamp_s is not None]
        for gap_index, (previous, current) in enumerate(
            zip(comparable_samples, comparable_samples[1:])
        ):
            assert previous.response_timestamp_s is not None
            assert current.response_timestamp_s is not None
            delta_ms = (current.response_timestamp_s - previous.response_timestamp_s) * 1000.0
            finish_gap_ms = (
                current.read_finish_monotonic - previous.read_finish_monotonic
            ) * 1000.0
            if delta_ms >= 0:
                gaps.append(
                    PeriodGap(
                        reader_index=reader_index,
                        gap_index=gap_index,
                        previous_timestamp_s=previous.response_timestamp_s,
                        current_timestamp_s=current.response_timestamp_s,
                        period_ms=delta_ms,
                        previous_finish_monotonic=previous.read_finish_monotonic,
                        current_finish_monotonic=current.read_finish_monotonic,
                        finish_gap_ms=finish_gap_ms,
                        previous_read_ms=previous.read_ms,
                        current_read_ms=current.read_ms,
                        py_cmd_gap_ms=_optional_gap_ms(
                            current.command_write_ts_ns, previous.command_write_ts_ns
                        ),
                        py_stdout_gap_ms=_optional_gap_ms(
                            current.stdout_line_received_ts_ns,
                            previous.stdout_line_received_ts_ns,
                        ),
                        runner_req_gap_ms=_optional_gap_ms(
                            current.runner_request_received_ts_ns,
                            previous.runner_request_received_ts_ns,
                        ),
                        runner_read_ms=_optional_duration_ms(
                            current.runner_read_end_ts_ns, current.runner_read_start_ts_ns
                        ),
                        runner_write_gap_ms=_optional_gap_ms(
                            current.runner_response_write_ts_ns,
                            previous.runner_response_write_ts_ns,
                        ),
                        pipe_back_ms=_optional_duration_ms(
                            current.stdout_line_received_ts_ns,
                            current.runner_response_write_ts_ns,
                        ),
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
    top_gaps = tuple(sorted(gaps, key=lambda gap: gap.period_ms, reverse=True)[:top_n])
    return ResponsePeriodStats(
        samples=len(values),
        mean_ms=mean_ms,
        max_ms=max(values),
        mean_abs_error_ms=abs(mean_ms - target_period_ms),
        worst_gap=top_gaps[0] if top_gaps else None,
        top_gaps=top_gaps,
    )


def _build_metrics(
    reader_stats: Sequence[ReaderStats],
    *,
    max_observed_concurrent_reads: int,
) -> LevelMetrics:
    read_errors = sum(item.read_errors for item in reader_stats)
    batch_mismatches = sum(item.batch_mismatches for item in reader_stats)
    missing_response_timestamps = sum(item.missing_response_timestamps for item in reader_stats)
    tick_samples_by_reader = tuple(tuple(item.tick_samples) for item in reader_stats)
    target_period_ms = 1000.0 / TARGET_HZ
    period_stats = evaluate_response_periods(
        tick_samples_by_reader,
        target_period_ms=target_period_ms,
        top_n=TOP_GAP_COUNT,
    )
    allowed_period_max_ms = target_period_ms * (1.0 + PERIOD_MAX_TOLERANCE_RATIO)
    allowed_period_mean_abs_error_ms = target_period_ms * PERIOD_MEAN_ERROR_RATIO
    value_count_ok = batch_mismatches == 0
    period_max_ok = period_stats.samples > 0 and period_stats.max_ms <= allowed_period_max_ms
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
        server_count=SERVER_COUNT,
        target_hz=TARGET_HZ,
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
    with fleet:
        yield


def _print_metrics(metrics: LevelMetrics) -> None:
    print()
    print("=" * 88)
    print("OPC UA multi-server bottleneck metrics")
    print("=" * 88)
    print(f"backend={os.environ.get('SOURCE_SIM_OPCUA_BACKEND', 'asyncua')}")
    print(f"client_backend={_client_backend_name()}")
    print(f"server_count={SERVER_COUNT}")
    print(f"target_hz={TARGET_HZ:.1f}")
    print(f"target_period_ms={metrics.target_period_ms:.1f}")
    print(f"allowed_period_max_ms={metrics.allowed_period_max_ms:.1f}")
    print(f"allowed_period_mean_abs_error_ms={metrics.allowed_period_mean_abs_error_ms:.2f}")
    print(f"duration={LOAD_LEVEL_DURATION_S:.1f}s")
    print(f"warmup={WARMUP_S:.1f}s")
    print(f"max_concurrent_reads={MAX_CONCURRENT_READS}")
    print(f"source_update_enabled={SOURCE_UPDATE_ENABLED}")
    print(f"source_update_hz={SOURCE_UPDATE_HZ:.1f}")
    print(f"period_max_tol={PERIOD_MAX_TOLERANCE_RATIO:.0%}")
    print(f"period_mean_error_tol={PERIOD_MEAN_ERROR_RATIO:.0%}")
    print("-" * 88)
    print(f"batch_mismatches={metrics.batch_mismatches}")
    print(f"period_samples={metrics.period_samples}")
    print(f"period_mean_ms={metrics.period_mean_ms:.2f}")
    print(f"period_max_ms={metrics.period_max_ms:.1f}")
    print(f"period_mean_abs_error_ms={metrics.period_mean_abs_error_ms:.2f}")
    print(f"read_errors={metrics.read_errors}")
    print(f"missing_response_timestamps={metrics.missing_response_timestamps}")
    print(f"value_count_ok={metrics.value_count_ok}")
    print(f"period_max_ok={metrics.period_max_ok}")
    print(f"period_mean_ok={metrics.period_mean_ok}")
    print(f"max_observed_concurrent_reads={metrics.max_observed_concurrent_reads}")
    print(f"status={'PASS' if metrics.passed else 'FAIL'}")
    if metrics.failure_reason:
        print(f"failure_reason={metrics.failure_reason}")
    print("=" * 88)


def _print_top_gaps(metrics: LevelMetrics) -> None:
    if not metrics.top_gaps:
        return
    print("top response period gaps:")
    print(
        "  reader  gap  period_ms  prev_resp_ts       cur_resp_ts        "
        "finish_gap_ms  prev_read_ms  cur_read_ms  py_cmd_gap_ms  "
        "py_stdout_gap_ms  runner_req_gap_ms  runner_read_ms  "
        "runner_write_gap_ms  pipe_back_ms"
    )
    for gap in metrics.top_gaps:
        print(
            f"  {gap.reader_index:>6} {gap.gap_index:>4} "
            f"{gap.period_ms:>10.1f} "
            f"{gap.previous_timestamp_s:>17.3f} "
            f"{gap.current_timestamp_s:>17.3f} "
            f"{gap.finish_gap_ms:>14.1f} "
            f"{gap.previous_read_ms:>13.1f} "
            f"{gap.current_read_ms:>11.1f} "
            f"{_format_optional_ms(gap.py_cmd_gap_ms)} "
            f"{_format_optional_ms(gap.py_stdout_gap_ms, width=17)} "
            f"{_format_optional_ms(gap.runner_req_gap_ms, width=17)} "
            f"{_format_optional_ms(gap.runner_read_ms, width=14)} "
            f"{_format_optional_ms(gap.runner_write_gap_ms, width=19)} "
            f"{_format_optional_ms(gap.pipe_back_ms, width=12)}"
        )
    print("=" * 88)


def _format_profiler_report(profiler: Any) -> ProfileSummary:
    if profiler is None:
        return ProfileSummary(duration_s=None, cpu_time_s=None, text="")

    text = profiler.output_text(unicode=True, color=False, show_all=SHOW_ALL_FRAMES)
    duration_s: float | None = None
    cpu_time_s: float | None = None

    session = getattr(profiler, "last_session", None)
    if session is not None:
        duration_s = _maybe_float(getattr(session, "duration", None))
        cpu_time_s = _maybe_float(getattr(session, "cpu_time", None))

    if duration_s is None or cpu_time_s is None:
        match = re.search(r"Duration:\s*([0-9.]+).*?CPU time:\s*([0-9.]+)", text)
        if match:
            duration_s = duration_s if duration_s is not None else float(match.group(1))
            cpu_time_s = cpu_time_s if cpu_time_s is not None else float(match.group(2))

    return ProfileSummary(duration_s=duration_s, cpu_time_s=cpu_time_s, text=text)


def _maybe_float(value: object) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _trim_text_lines(text: str, *, max_lines: int) -> str:
    if max_lines <= 0:
        return text
    lines = text.splitlines()
    if len(lines) <= max_lines:
        return text
    kept = lines[:max_lines]
    kept.append(f"... <trimmed {len(lines) - max_lines} lines; set SOURCE_SIM_PROFILE_SHOW_ALL=true or SOURCE_SIM_PROFILE_MAX_LINES=0 to show all>")
    return "\n".join(kept)


def _build_diagnosis(metrics: LevelMetrics, profile: ProfileSummary) -> Diagnosis:
    cpu_ratio: float | None = None
    if profile.duration_s and profile.duration_s > 0 and profile.cpu_time_s is not None:
        cpu_ratio = profile.cpu_time_s / profile.duration_s

    python_cpu_bound = bool(cpu_ratio is not None and cpu_ratio >= 0.8)
    not_python_cpu_bound = bool(cpu_ratio is not None and cpu_ratio < 0.5)

    profile_text_lower = profile.text.lower()
    asyncua_binary_codec_hotspot = _client_backend_name().lower() == "asyncua" and any(
        marker in profile_text_lower
        for marker in (
            "asyncua.ua.ua_binary",
            "struct_from_binary",
            "variant_from_binary",
            "deserialize",
        )
    )

    max_top_gap_cur_read_ms = max(
        (gap.current_read_ms for gap in metrics.top_gaps),
        default=0.0,
    )

    pmax_failed = metrics.period_samples > 0 and not metrics.period_max_ok
    scheduler_or_external_timestamp_jitter = bool(
        pmax_failed and max_top_gap_cur_read_ms < metrics.allowed_period_max_ms * 0.5
    )
    slow_read_tick = bool(
        pmax_failed and max_top_gap_cur_read_ms >= metrics.allowed_period_max_ms * 0.8
    )

    if asyncua_binary_codec_hotspot:
        conclusion = (
            "asyncua client is dominated by Python OPC UA binary codec cost; "
            "compare with open62541 client for server/pipe jitter."
        )
    elif not_python_cpu_bound and scheduler_or_external_timestamp_jitter:
        conclusion = (
            "Python CPU is not the bottleneck. pmax spike is not caused by a slow "
            "read_prepared_raw() tick. Next step should instrument open62541 client "
            "runner protocol timestamps."
        )
    elif slow_read_tick:
        conclusion = (
            "pmax spike coincides with slow read_prepared_raw(); continue into client "
            "read path / runner read timing."
        )
    elif not_python_cpu_bound:
        conclusion = (
            "Python CPU is not the bottleneck. Use top gap timing fields to decide "
            "whether to instrument runner timestamps next."
        )
    elif python_cpu_bound:
        conclusion = "Python CPU appears high; inspect compact pyinstrument hotspots."
    else:
        conclusion = "Diagnosis is inconclusive; inspect top gaps and compact pyinstrument output."

    return Diagnosis(
        not_python_cpu_bound=not_python_cpu_bound,
        python_cpu_bound=python_cpu_bound,
        asyncua_binary_codec_hotspot=asyncua_binary_codec_hotspot,
        slow_read_tick=slow_read_tick,
        scheduler_or_external_timestamp_jitter=scheduler_or_external_timestamp_jitter,
        cpu_ratio=cpu_ratio,
        max_top_gap_cur_read_ms=max_top_gap_cur_read_ms,
        conclusion=conclusion,
    )


def _print_diagnosis(diagnosis: Diagnosis) -> None:
    print()
    print("=" * 88)
    print("diagnosis")
    print("=" * 88)
    if diagnosis.cpu_ratio is None:
        print("cpu_ratio=unknown")
    else:
        print(f"cpu_ratio={diagnosis.cpu_ratio:.3f}")
    print(f"not_python_cpu_bound={diagnosis.not_python_cpu_bound}")
    print(f"python_cpu_bound={diagnosis.python_cpu_bound}")
    print(f"asyncua_binary_codec_hotspot={diagnosis.asyncua_binary_codec_hotspot}")
    print(f"slow_read_tick={diagnosis.slow_read_tick}")
    print(
        "scheduler_or_external_timestamp_jitter="
        f"{diagnosis.scheduler_or_external_timestamp_jitter}"
    )
    print(f"max_top_gap_cur_read_ms={diagnosis.max_top_gap_cur_read_ms:.1f}")
    print()
    print("conclusion:")
    print(f"  {diagnosis.conclusion}")
    print("=" * 88)


def _print_profiler_report(profile: ProfileSummary) -> None:
    print()
    print("=" * 88)
    print("pyinstrument call-stack profile")
    print("=" * 88)
    if not profile.text:
        print("pyinstrument is not installed; profiler output skipped.")
    else:
        print(_trim_text_lines(profile.text, max_lines=PROFILE_MAX_LINES))
    print("=" * 88)


@pytest.mark.load
def test_source_simulation_multi_server_profile() -> None:
    if PROCESS_COUNT != 1:
        raise ValueError(
            "multi-process profile is not implemented; set "
            "SOURCE_SIM_LOAD_PROCESS_COUNT=1 or use the capacity test worker logic first"
        )
    if COROUTINES_PER_PROCESS not in (0, 1):
        raise ValueError(
            "this profile runs one coroutine scheduler in the current process; set "
            "SOURCE_SIM_LOAD_COROUTINES_PER_PROCESS=0 or 1"
        )
    if SERVER_COUNT <= 0:
        raise ValueError("SOURCE_SIM_LOAD_SERVER_COUNT must be greater than 0")
    if TARGET_HZ <= 0:
        raise ValueError("SOURCE_SIM_LOAD_TARGET_HZ must be greater than 0")
    if MAX_CONCURRENT_READS <= 0:
        raise ValueError("SOURCE_SIM_LOAD_MAX_CONCURRENT_READS must be greater than 0")

    base_source = build_opcua_source_from_repository(
        min_expected_point_count=MIN_EXPECTED_POINT_COUNT,
        max_expected_point_count=MAX_EXPECTED_POINT_COUNT,
    )
    sources = build_multi_sources(base_source, server_count=SERVER_COUNT)
    profiler = Profiler(async_mode="enabled") if Profiler is not None else None

    with _started_fleet(sources):
        if profiler is not None:
            profiler.start()
            try:
                metrics = asyncio.run(_run_profile_level(sources))
            finally:
                profiler.stop()
        else:
            metrics = asyncio.run(_run_profile_level(sources))

    profile = _format_profiler_report(profiler)
    diagnosis = _build_diagnosis(metrics, profile)

    _print_metrics(metrics)
    _print_top_gaps(metrics)
    _print_diagnosis(diagnosis)
    _print_profiler_report(profile)
    assert metrics.period_samples >= 0
