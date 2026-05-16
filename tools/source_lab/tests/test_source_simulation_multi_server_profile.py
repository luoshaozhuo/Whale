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
from typing import Any, Literal

import pytest

try:
    from pyinstrument import Profiler
except ImportError:  # pragma: no cover - optional dependency
    Profiler = None  # type: ignore[assignment]

from whale.shared.source.models import SourceConnectionProfile
from whale.shared.source.opcua.backends import PreparedReadPlan
from whale.shared.source.opcua.backends.open62541_backend import (
    Open62541OpcUaClientBackend,
    Open62541StreamReadResult,
)
from whale.shared.source.opcua.reader import OpcUaSourceReader
from whale.shared.source.scheduling import (
    PollingErrorEvent,
    PollingJobSpec,
    PollingResultEvent,
    PollingTickDiagnostics,
    ReadConcurrencyLimiter,
    SourcePollingScheduler,
    build_even_stagger_offsets,
)
from whale.shared.source.scheduling.fixed_rate import HighFrequencyFixedRateScheduler
from tools.source_lab.opcua.address_space import logical_path
from tools.source_lab.model import SimulatedSource, UpdateConfig
from tools.source_lab.fleet import SourceSimulatorFleet
from tools.source_lab.tests.support.sources import (
    build_multi_sources,
    build_opcua_endpoint,
    build_opcua_source_from_repository,
)

# Acceptance modes:
# - source_polling_scheduler: original general-purpose baseline
# - high_frequency_coarse_sleep_spin: Python-layer best-effort comparison mode
# - open62541_runner_poll: current validated high-frequency profile mode
#
# Diagnostic-only modes. Do not use as acceptance mode:
# - absolute
# - high_frequency_fixed_rate
# - high_frequency_central_ticker
# - high_frequency_grouped_reader_loop
SchedulerMode = Literal[
    "source_polling_scheduler",
    "absolute",
    "high_frequency_fixed_rate",
    "high_frequency_central_ticker",
    "high_frequency_coarse_sleep_spin",
    "high_frequency_grouped_reader_loop",
    "open62541_runner_poll",
]
SchedulerCallbackMode = Literal["queue", "inline", "disabled"]
AbsoluteBaseMode = Literal["measure_start", "scheduler_start"]
SchedulerExecutionMode = Literal["normal", "minimal"]
SchedulerLoopMode = Literal["normal", "no_skip_missed", "absolute_clone"]
SchedulerStartMode = Literal[
    "normal", "yield_after_create", "barrier", "delayed_base_after_tasks"
]
SchedulerImpl = Literal["default", "absolute_direct", "central_ticker", "coarse_sleep_spin", "grouped_reader_loop"]

# Legacy diagnostic environment variables remain parseable in this profile
# module for historical replay of non-validated experiments. The production
# SourcePollingScheduler no longer uses these branches.


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


def _env_scheduler_mode(
    name: str, default: str = "source_polling_scheduler"
) -> SchedulerMode:
    value = os.environ.get(name)
    if value is None or value.strip() == "":
        return default

    normalized = value.strip().lower()
    allowed = {
        "source_polling_scheduler",
        "absolute",
        "high_frequency_fixed_rate",
        "high_frequency_central_ticker",
        "high_frequency_coarse_sleep_spin",
        "high_frequency_grouped_reader_loop",
        "open62541_runner_poll",
    }
    if normalized not in allowed:
        raise ValueError(
            f"{name} must be one of {sorted(allowed)}; got {value!r}"
        )
    return normalized


def _env_scheduler_callback_mode(
    name: str, default: str = "queue"
) -> SchedulerCallbackMode:
    value = os.environ.get(name)
    if value is None or value.strip() == "":
        return default

    normalized = value.strip().lower()
    allowed = {"queue", "inline", "disabled"}
    if normalized not in allowed:
        raise ValueError(
            f"{name} must be one of {sorted(allowed)}; got {value!r}"
        )
    return normalized


def _env_absolute_base_mode(
    name: str, default: str = "measure_start"
) -> AbsoluteBaseMode:
    value = os.environ.get(name)
    if value is None or value.strip() == "":
        return default

    normalized = value.strip().lower()
    allowed = {"measure_start", "scheduler_start"}
    if normalized not in allowed:
        raise ValueError(
            f"{name} must be one of {sorted(allowed)}; got {value!r}"
        )
    return normalized


def _env_scheduler_execution_mode(
    name: str, default: str = "normal"
) -> SchedulerExecutionMode:
    value = os.environ.get(name)
    if value is None or value.strip() == "":
        return default

    normalized = value.strip().lower()
    allowed = {"normal", "minimal"}
    if normalized not in allowed:
        raise ValueError(
            f"{name} must be one of {sorted(allowed)}; got {value!r}"
        )
    return normalized


def _env_scheduler_loop_mode(
    name: str, default: str = "normal"
) -> SchedulerLoopMode:
    value = os.environ.get(name)
    if value is None or value.strip() == "":
        return default

    normalized = value.strip().lower()
    allowed = {"normal", "no_skip_missed", "absolute_clone"}
    if normalized not in allowed:
        raise ValueError(
            f"{name} must be one of {sorted(allowed)}; got {value!r}"
        )
    return normalized


def _env_scheduler_start_mode(
    name: str, default: str = "normal"
) -> SchedulerStartMode:
    value = os.environ.get(name)
    if value is None or value.strip() == "":
        return default

    normalized = value.strip().lower()
    allowed = {"normal", "yield_after_create", "barrier", "delayed_base_after_tasks"}
    if normalized not in allowed:
        raise ValueError(
            f"{name} must be one of {sorted(allowed)}; got {value!r}"
        )
    return normalized


def _env_scheduler_impl(
    name: str, default: str = "default"
) -> SchedulerImpl:
    value = os.environ.get(name)
    if value is None or value.strip() == "":
        return default

    normalized = value.strip().lower()
    allowed = {
        "default",
        "absolute_direct",
        "central_ticker",
        "coarse_sleep_spin",
        "grouped_reader_loop",
    }
    if normalized not in allowed:
        raise ValueError(
            f"{name} must be one of {sorted(allowed)}; got {value!r}"
        )
    return normalized


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


def _optional_monotonic_duration_ms(end: float | None, start: float | None) -> float | None:
    if end is None or start is None:
        return None
    return max(0.0, (end - start) * 1000.0)


def _debug_timing_kwargs(debug_timing: object | None) -> dict[str, int | None]:
    return {
        "command_write_ts_ns": getattr(debug_timing, "command_write_ts_ns", None),
        "command_drain_done_ts_ns": getattr(debug_timing, "command_drain_done_ts_ns", None),
        "stdout_line_received_ts_ns": getattr(debug_timing, "stdout_line_received_ts_ns", None),
        "runner_request_received_ts_ns": getattr(debug_timing, "runner_request_received_ts_ns", None),
        "runner_scheduled_ts_ns": getattr(debug_timing, "runner_scheduled_ts_ns", None),
        "runner_read_start_ts_ns": getattr(debug_timing, "runner_read_start_ts_ns", None),
        "runner_read_end_ts_ns": getattr(debug_timing, "runner_read_end_ts_ns", None),
        "runner_response_write_ts_ns": getattr(debug_timing, "runner_response_write_ts_ns", None),
    }


def _sample_diagnostics_kwargs(
    diagnostics: PollingTickDiagnostics | None,
) -> dict[str, float | int | str | tuple[str, ...] | None]:
    if diagnostics is None:
        return {
            "sleep_woke_at_monotonic": None,
            "limiter_wait_start_at_monotonic": None,
            "limiter_acquired_at_monotonic": None,
            "operation_start_at_monotonic": None,
            "operation_finished_at_monotonic": None,
            "callback_enqueue_at_monotonic": None,
            "task_count": None,
            "relevant_task_names": None,
        }
    return {
        "sleep_woke_at_monotonic": diagnostics.sleep_woke_at,
        "limiter_wait_start_at_monotonic": diagnostics.limiter_wait_start_at,
        "limiter_acquired_at_monotonic": diagnostics.limiter_acquired_at,
        "operation_start_at_monotonic": diagnostics.operation_start_at,
        "operation_finished_at_monotonic": diagnostics.operation_finished_at,
        "callback_enqueue_at_monotonic": diagnostics.callback_enqueue_at,
        "task_count": diagnostics.task_count,
        "relevant_task_names": diagnostics.relevant_task_names,
    }


def _tick_result_from_stream_item(
    item: Open62541StreamReadResult,
    *,
    expected_value_count: int,
) -> TickResult:
    """Map one runner stream payload into the existing tick-result shape."""

    debug_timing = item.debug_timing
    read_start_ns = getattr(debug_timing, "runner_read_start_ts_ns", None)
    read_end_ns = getattr(debug_timing, "runner_read_end_ts_ns", None)
    read_start_monotonic = (
        read_start_ns / 1_000_000_000.0 if isinstance(read_start_ns, int) and read_start_ns > 0 else 0.0
    )
    read_finish_monotonic = (
        read_end_ns / 1_000_000_000.0 if isinstance(read_end_ns, int) and read_end_ns > 0 else read_start_monotonic
    )
    elapsed_ms = max(0.0, (read_finish_monotonic - read_start_monotonic) * 1000.0)
    response_timestamp_s = (
        item.response_timestamp.timestamp()
        if isinstance(item.response_timestamp, datetime)
        else None
    )

    if not item.ok:
        return TickResult(
            False,
            item.value_count,
            elapsed_ms,
            response_timestamp_s,
            read_start_monotonic,
            read_finish_monotonic,
            item.detail or "read_failed",
            **_debug_timing_kwargs(debug_timing),
        )
    if item.value_count != expected_value_count:
        return TickResult(
            False,
            item.value_count,
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
            item.value_count,
            elapsed_ms,
            None,
            read_start_monotonic,
            read_finish_monotonic,
            "missing_response_timestamp",
            **_debug_timing_kwargs(debug_timing),
        )
    return TickResult(
        True,
        item.value_count,
        elapsed_ms,
        response_timestamp_s,
        read_start_monotonic,
        read_finish_monotonic,
        **_debug_timing_kwargs(debug_timing),
    )


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
SCHEDULER_MODE = _env_scheduler_mode("SOURCE_SIM_PROFILE_SCHEDULER_MODE")
SCHEDULER_CALLBACK_MODE = _env_scheduler_callback_mode(
    "SOURCE_SIM_PROFILE_SCHEDULER_CALLBACK_MODE"
)
ABSOLUTE_BASE_MODE = _env_absolute_base_mode("SOURCE_SIM_PROFILE_ABSOLUTE_BASE")
SCHEDULER_EXECUTION_MODE = _env_scheduler_execution_mode(
    "SOURCE_SIM_PROFILE_SCHEDULER_EXECUTION_MODE"
)
SCHEDULER_LOOP_MODE = _env_scheduler_loop_mode(
    "SOURCE_SIM_PROFILE_SCHEDULER_LOOP_MODE"
)
SCHEDULER_START_MODE = _env_scheduler_start_mode(
    "SOURCE_SIM_PROFILE_SCHEDULER_START_MODE"
)
SCHEDULER_IMPL = _env_scheduler_impl("SOURCE_SIM_PROFILE_SCHEDULER_IMPL")
PRINT_SCHEDULER_STRUCTURE = _env_flag(
    "SOURCE_SIM_PROFILE_PRINT_SCHEDULER_STRUCTURE",
    False,
)
PRINT_TASK_CREATION = _env_flag(
    "SOURCE_SIM_PROFILE_PRINT_TASK_CREATION",
    False,
)
USE_UVLOOP = _env_flag("SOURCE_SIM_PROFILE_USE_UVLOOP", False)
SCHEDULER_GROUP_COUNT = _env_int("SOURCE_SIM_PROFILE_SCHEDULER_GROUP_COUNT", 2)


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
    runner_scheduled_ts_ns: int | None = None
    runner_read_start_ts_ns: int | None = None
    runner_read_end_ts_ns: int | None = None
    runner_response_write_ts_ns: int | None = None


@dataclass(frozen=True, slots=True)
class TickSample:
    scheduler_mode: str | None
    task_name: str | None
    job_id: str | None
    reader_index: int
    tick_index: int
    scheduler_base_time: float | None
    first_run_at: float | None
    offset_seconds: float | None
    interval_seconds: float | None
    scheduled_at_monotonic: float
    actual_start_monotonic: float
    read_start_monotonic: float
    read_finish_monotonic: float
    response_timestamp_s: float | None
    value_count: int | None
    error: str | None
    sleep_woke_at_monotonic: float | None = None
    limiter_wait_start_at_monotonic: float | None = None
    limiter_acquired_at_monotonic: float | None = None
    operation_start_at_monotonic: float | None = None
    operation_finished_at_monotonic: float | None = None
    callback_enqueue_at_monotonic: float | None = None
    task_count: int | None = None
    relevant_task_names: tuple[str, ...] | None = None
    command_write_ts_ns: int | None = None
    command_drain_done_ts_ns: int | None = None
    stdout_line_received_ts_ns: int | None = None
    runner_request_received_ts_ns: int | None = None
    runner_scheduled_ts_ns: int | None = None
    runner_read_start_ts_ns: int | None = None
    runner_read_end_ts_ns: int | None = None
    runner_response_write_ts_ns: int | None = None

    @property
    def read_ms(self) -> float:
        return max(0.0, (self.read_finish_monotonic - self.read_start_monotonic) * 1000.0)

    @property
    def schedule_lag_ms(self) -> float:
        return max(
            0.0,
            (self.actual_start_monotonic - self.scheduled_at_monotonic) * 1000.0,
        )

    @property
    def sleep_wake_lag_ms(self) -> float | None:
        return _optional_monotonic_duration_ms(
            self.sleep_woke_at_monotonic,
            self.scheduled_at_monotonic,
        )

    @property
    def limiter_wait_ms(self) -> float | None:
        return _optional_monotonic_duration_ms(
            self.limiter_acquired_at_monotonic,
            self.limiter_wait_start_at_monotonic,
        )

    @property
    def pre_operation_overhead_ms(self) -> float | None:
        return _optional_monotonic_duration_ms(
            self.operation_start_at_monotonic,
            self.limiter_acquired_at_monotonic,
        )

    @property
    def operation_ms(self) -> float | None:
        return _optional_monotonic_duration_ms(
            self.operation_finished_at_monotonic,
            self.operation_start_at_monotonic,
        )

    @property
    def callback_enqueue_ms(self) -> float | None:
        return _optional_monotonic_duration_ms(
            self.callback_enqueue_at_monotonic,
            self.operation_finished_at_monotonic,
        )


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
class TaskCreationSample:
    scheduler_mode: str
    reader_index: int
    task_name: str | None
    scheduler_start_called_at: float | None
    scheduler_base_time: float | None
    task_create_start_at: float | None
    per_task_created_at: float | None
    all_tasks_created_at: float | None
    task_first_entered_at: float | None
    first_run_at: float | None
    first_scheduled_at: float | None
    first_sleep_delay_ms: float | None
    first_sleep_entered_at: float | None
    first_sleep_woke_at: float | None
    first_sleep_wake_lag_ms: float | None


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
    previous_schedule_lag_ms: float
    current_schedule_lag_ms: float
    schedule_gap_ms: float
    previous_sleep_wake_lag_ms: float | None = None
    current_sleep_wake_lag_ms: float | None = None
    previous_limiter_wait_ms: float | None = None
    current_limiter_wait_ms: float | None = None
    previous_pre_operation_overhead_ms: float | None = None
    current_pre_operation_overhead_ms: float | None = None
    previous_operation_ms: float | None = None
    current_operation_ms: float | None = None
    previous_callback_enqueue_ms: float | None = None
    current_callback_enqueue_ms: float | None = None
    c_scheduled_period_ms: float | None = None
    c_read_start_period_ms: float | None = None
    c_read_end_period_ms: float | None = None
    py_stdout_period_ms: float | None = None
    runner_read_ms: float | None = None
    pipe_back_ms: float | None = None
    c_response_write_period_ms: float | None = None

    @property
    def finish_period_ms(self) -> float:
        return self.finish_gap_ms

    @property
    def response_period_ms(self) -> float:
        return self.period_ms


GapClassification = Literal[
    "c_schedule_spike",
    "c_read_start_spike",
    "python_receive_spike",
    "c_response_write_spike",
    "response_timestamp_only_spike",
    "mixed_spike",
    "unknown",
]


@dataclass(frozen=True, slots=True)
class ClassifiedPeriodGap:
    gap: PeriodGap
    classification: GapClassification


@dataclass(frozen=True, slots=True)
class GapClassificationSummary:
    c_schedule_spike: int = 0
    c_read_start_spike: int = 0
    python_receive_spike: int = 0
    c_response_write_spike: int = 0
    response_timestamp_only_spike: int = 0
    mixed_spike: int = 0
    unknown: int = 0


@dataclass(frozen=True, slots=True)
class PeriodDecompositionSummary:
    gap_classification_summary: GapClassificationSummary
    max_c_scheduled_period_ms: float | None
    max_c_read_start_period_ms: float | None
    max_c_read_end_period_ms: float | None
    max_c_response_write_period_ms: float | None
    max_py_stdout_period_ms: float | None
    max_response_period_ms: float | None
    max_runner_read_ms: float | None
    max_pipe_back_ms: float | None
    classified_top_gaps: tuple[ClassifiedPeriodGap, ...]


@dataclass(frozen=True, slots=True)
class LevelMetrics:
    use_uvloop: bool
    scheduler_mode: SchedulerMode
    scheduler_callback_mode: SchedulerCallbackMode
    scheduler_loop_mode: SchedulerLoopMode
    scheduler_start_mode: SchedulerStartMode
    absolute_base: AbsoluteBaseMode
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
    period_decomposition: PeriodDecompositionSummary


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


@dataclass(frozen=True, slots=True)
class ProfileRunResult:
    metrics: LevelMetrics
    tick_samples_by_reader: tuple[tuple[TickSample, ...], ...]
    task_creation_samples: tuple[TaskCreationSample, ...]


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

    def _open62541_backend_or_raise(self) -> Open62541OpcUaClientBackend:
        if self._reader is None:
            raise RuntimeError("reader_not_connected")
        backend = getattr(self._reader, "_backend", None)
        if not isinstance(backend, Open62541OpcUaClientBackend):
            raise TypeError(
                "open62541_runner_poll requires Open62541OpcUaClientBackend"
            )
        return backend

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

    async def stream_runner_poll(
        self,
        *,
        expected_value_count: int,
        target_hz: float,
        warmup_s: float,
        duration_s: float,
    ) -> tuple[TickResult, ...]:
        """Collect one runner-internal polling stream and map it into tick results."""

        if self._plan is None:
            raise RuntimeError("reader_not_connected")

        backend = self._open62541_backend_or_raise()
        ticks: list[TickResult] = []
        async for item in backend.stream_prepared_raw_poll(
            self._plan,
            target_hz=target_hz,
            warmup_s=warmup_s,
            duration_s=duration_s,
        ):
            ticks.append(
                _tick_result_from_stream_item(
                    item,
                    expected_value_count=expected_value_count,
                )
            )
        return tuple(ticks)


async def _run_bounded(
    readers: Sequence[OpcUaProfileReader],
    action: Callable[[OpcUaProfileReader], Awaitable[object]],
) -> None:
    semaphore = asyncio.Semaphore(max(1, min(MAX_CONCURRENT_READS, 8)))

    async def run_one(reader: OpcUaProfileReader) -> None:
        async with semaphore:
            await asyncio.wait_for(action(reader), timeout=max(READ_TIMEOUT_S, 10.0))

    await asyncio.gather(*(run_one(reader) for reader in readers))


def _capture_relevant_task_snapshot(
    loop: asyncio.AbstractEventLoop,
) -> tuple[int, tuple[str, ...]]:
    relevant_prefixes = (
        "source-polling:",
        "source-polling-callback:",
        "profile-absolute:",
    )
    all_tasks = asyncio.all_tasks(loop)
    relevant_task_names = tuple(
        sorted(
            task.get_name()
            for task in all_tasks
            if any(task.get_name().startswith(prefix) for prefix in relevant_prefixes)
        )
    )
    return len(all_tasks), relevant_task_names


def _source_scheduler_mode_label() -> str:
    return (
        f"{SCHEDULER_MODE}:{SCHEDULER_EXECUTION_MODE}:"
        f"{SCHEDULER_LOOP_MODE}:{SCHEDULER_START_MODE}:{SCHEDULER_IMPL}"
    )


def _scheduler_task_creation_samples(
    scheduler: SourcePollingScheduler[TickResult],
) -> tuple[TaskCreationSample, ...]:
    samples: list[TaskCreationSample] = []
    for diagnostics in scheduler._task_creation_snapshot():  # type: ignore[attr-defined]
        reader_index = int(diagnostics.job_id.rsplit("-", 1)[-1])
        samples.append(
            TaskCreationSample(
                scheduler_mode=_source_scheduler_mode_label(),
                reader_index=reader_index,
                task_name=diagnostics.task_name,
                scheduler_start_called_at=diagnostics.scheduler_start_called_at,
                scheduler_base_time=diagnostics.scheduler_base_time,
                task_create_start_at=diagnostics.task_create_start_at,
                per_task_created_at=diagnostics.per_job_task_created_at,
                all_tasks_created_at=diagnostics.all_tasks_created_at,
                task_first_entered_at=diagnostics.run_job_first_entered_at,
                first_run_at=diagnostics.first_run_at,
                first_scheduled_at=diagnostics.first_scheduled_at,
                first_sleep_delay_ms=diagnostics.first_sleep_delay_ms,
                first_sleep_entered_at=diagnostics.first_sleep_entered_at,
                first_sleep_woke_at=diagnostics.first_sleep_woke_at,
                first_sleep_wake_lag_ms=diagnostics.first_sleep_wake_lag_ms,
            )
        )
    return tuple(sorted(samples, key=lambda item: item.reader_index))


async def _run_profile_level(sources: Sequence[SimulatedSource]) -> ProfileRunResult:
    readers = tuple(OpcUaProfileReader(source) for source in sources)
    reader_stats = [ReaderStats() for _ in readers]
    expected_value_count = len(sources[0].points)
    interval_seconds = 1.0 / TARGET_HZ
    offsets = build_even_stagger_offsets(count=len(readers), interval_seconds=interval_seconds)

    limiter = ReadConcurrencyLimiter[TickResult](max_concurrent=MAX_CONCURRENT_READS)
    loop = asyncio.get_running_loop()
    measure_start_at = loop.time() + WARMUP_S
    measure_end_at = measure_start_at + LOAD_LEVEL_DURATION_S

    if (
        SCHEDULER_MODE == "open62541_runner_poll"
        and _client_backend_name().strip().lower() != "open62541"
    ):
        raise ValueError(
            "SOURCE_SIM_PROFILE_SCHEDULER_MODE=open62541_runner_poll requires "
            "SOURCE_SIM_OPCUA_CLIENT_BACKEND=open62541"
        )

    def record_scheduler_event(event: object) -> None:
        if isinstance(event, PollingResultEvent):
            reader_index = int(event.job_id.rsplit("-", 1)[-1])
            if measure_start_at <= event.finished_at <= measure_end_at:
                _record_tick(
                    reader_stats[reader_index],
                    event.result,
                    scheduler_mode=(
                        _source_scheduler_mode_label()
                        if SCHEDULER_MODE == "source_polling_scheduler"
                        else SCHEDULER_MODE
                    ),
                    job_id=event.job_id,
                    reader_index=reader_index,
                    scheduled_at_monotonic=event.scheduled_at,
                    actual_start_monotonic=event.started_at,
                    diagnostics=event.diagnostics,
                )
            return
        if isinstance(event, PollingErrorEvent):
            reader_index = int(event.job_id.rsplit("-", 1)[-1])
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
                    scheduler_mode=(
                        _source_scheduler_mode_label()
                        if SCHEDULER_MODE == "source_polling_scheduler"
                        else SCHEDULER_MODE
                    ),
                    job_id=event.job_id,
                    reader_index=reader_index,
                    scheduled_at_monotonic=event.scheduled_at,
                    actual_start_monotonic=event.started_at,
                    diagnostics=event.diagnostics,
                )

    await _run_bounded(readers, lambda reader: reader.connect())
    try:
        scheduler_start_at = loop.time()
        task_creation_samples: tuple[TaskCreationSample, ...]
        if SCHEDULER_MODE == "source_polling_scheduler":
            task_creation_samples = await _run_source_polling_scheduler(
                readers=readers,
                expected_value_count=expected_value_count,
                interval_seconds=interval_seconds,
                offsets=offsets,
                limiter=limiter,
                event_sink=record_scheduler_event,
            )
        elif SCHEDULER_MODE == "high_frequency_fixed_rate":
            task_creation_samples = await _run_high_frequency_fixed_rate_scheduler(
                readers=readers,
                expected_value_count=expected_value_count,
                interval_seconds=interval_seconds,
                offsets=offsets,
                limiter=limiter,
                event_sink=record_scheduler_event,
                scheduler_start_at=scheduler_start_at,
                measure_start_at=measure_start_at,
            )
        elif SCHEDULER_MODE == "high_frequency_central_ticker":
            task_creation_samples = await _run_high_frequency_central_ticker_scheduler(
                readers=readers,
                expected_value_count=expected_value_count,
                interval_seconds=interval_seconds,
                offsets=offsets,
                limiter=limiter,
                event_sink=record_scheduler_event,
                scheduler_start_at=scheduler_start_at,
                measure_start_at=measure_start_at,
            )
        elif SCHEDULER_MODE == "high_frequency_coarse_sleep_spin":
            task_creation_samples = await _run_high_frequency_coarse_sleep_spin_scheduler(
                readers=readers,
                reader_stats=reader_stats,
                expected_value_count=expected_value_count,
                interval_seconds=interval_seconds,
                offsets=offsets,
                limiter=limiter,
                measure_start_at=measure_start_at,
                measure_end_at=measure_end_at,
                scheduler_start_at=scheduler_start_at,
            )
        elif SCHEDULER_MODE == "open62541_runner_poll":
            task_creation_samples = await _run_open62541_runner_poll_mode(
                readers=readers,
                reader_stats=reader_stats,
                expected_value_count=expected_value_count,
            )
        elif SCHEDULER_MODE == "high_frequency_grouped_reader_loop":
            task_creation_samples = await _run_high_frequency_grouped_reader_loop_scheduler(
                readers=readers,
                expected_value_count=expected_value_count,
                interval_seconds=interval_seconds,
                offsets=offsets,
                limiter=limiter,
                event_sink=record_scheduler_event,
                scheduler_start_at=scheduler_start_at,
                measure_start_at=measure_start_at,
            )
        else:
            task_creation_samples = await _run_absolute_scheduler(
                readers=readers,
                reader_stats=reader_stats,
                expected_value_count=expected_value_count,
                interval_seconds=interval_seconds,
                offsets=offsets,
                limiter=limiter,
                measure_start_at=measure_start_at,
                measure_end_at=measure_end_at,
                scheduler_start_at=scheduler_start_at,
            )
    finally:
        await _run_bounded(readers, lambda reader: reader.close())

    concurrency = await limiter.snapshot()
    max_observed_concurrent_reads = (
        len(readers)
        if SCHEDULER_MODE == "open62541_runner_poll"
        else concurrency.max_observed_active
    )
    return ProfileRunResult(
        metrics=_build_metrics(
            reader_stats,
            max_observed_concurrent_reads=max_observed_concurrent_reads,
        ),
        tick_samples_by_reader=tuple(tuple(item.tick_samples) for item in reader_stats),
        task_creation_samples=task_creation_samples,
    )


async def _run_source_polling_scheduler(
    *,
    readers: Sequence[OpcUaProfileReader],
    expected_value_count: int,
    interval_seconds: float,
    offsets: Sequence[float],
    limiter: ReadConcurrencyLimiter[TickResult],
    event_sink: Callable[[object], None],
) -> tuple[TaskCreationSample, ...]:
    scheduler = SourcePollingScheduler[TickResult](limiter=limiter, diagnostics_enabled=False)
    scheduler._event_sink = event_sink  # type: ignore[attr-defined]

    async def on_result(_event: PollingResultEvent[TickResult]) -> None:
        return None

    async def on_error(_event: PollingErrorEvent) -> None:
        return None

    for index, reader in enumerate(readers):

        async def operation(*, reader: OpcUaProfileReader = reader) -> TickResult:
            return await reader.read_tick(expected_value_count=expected_value_count)

        scheduler.add_job(
            PollingJobSpec[TickResult](
                job_id=f"opcua-reader-{index}",
                interval_seconds=interval_seconds,
                offset_seconds=offsets[index],
                timeout_seconds=READ_TIMEOUT_S,
                operation=operation,
                on_result=on_result,
                on_error=on_error,
            )
        )

    await scheduler.start()
    try:
        await asyncio.sleep(WARMUP_S + LOAD_LEVEL_DURATION_S)
    finally:
        await scheduler.stop()
    return _scheduler_task_creation_samples(scheduler)


async def _run_absolute_scheduler(
    *,
    readers: Sequence[OpcUaProfileReader],
    reader_stats: Sequence[ReaderStats],
    expected_value_count: int,
    interval_seconds: float,
    offsets: Sequence[float],
    limiter: ReadConcurrencyLimiter[TickResult],
    measure_start_at: float,
    measure_end_at: float,
    scheduler_start_at: float,
) -> tuple[TaskCreationSample, ...]:
    loop = asyncio.get_running_loop()
    stop_at = measure_end_at
    absolute_start_called_at = loop.time()
    absolute_base_time = (
        measure_start_at
        if ABSOLUTE_BASE_MODE == "measure_start"
        else scheduler_start_at
    )
    task_create_start_at = loop.time()
    task_creation_samples: list[TaskCreationSample] = []
    per_task_created_times: dict[int, float] = {}
    all_tasks_created_at: float | None = None

    async def run_reader(reader_index: int, reader: OpcUaProfileReader, offset_seconds: float) -> None:
        base_time = absolute_base_time
        task_name = (
            asyncio.current_task().get_name()
            if asyncio.current_task() is not None
            else None
        )
        first_entered_at = loop.time()
        first_run_at = base_time + offset_seconds
        first_scheduled_at = first_run_at
        tick_index = 0
        first_sleep_delay_ms: float | None = None
        first_sleep_entered_at: float | None = None
        first_sleep_woke_at: float | None = None
        first_sleep_wake_lag_ms: float | None = None
        while True:
            scheduled_at = base_time + offset_seconds + (tick_index * interval_seconds)
            if scheduled_at > stop_at:
                return

            delay_seconds = scheduled_at - loop.time()
            if tick_index == 0:
                first_sleep_delay_ms = max(0.0, delay_seconds * 1000.0)
                first_sleep_entered_at = loop.time()
            if delay_seconds > 0:
                await asyncio.sleep(delay_seconds)
            sleep_woke_at = loop.time()
            if tick_index == 0:
                first_sleep_woke_at = sleep_woke_at
                first_sleep_wake_lag_ms = max(
                    0.0,
                    (sleep_woke_at - scheduled_at) * 1000.0,
                )
                task_creation_samples.append(
                    TaskCreationSample(
                        scheduler_mode="absolute",
                        reader_index=reader_index,
                        task_name=task_name,
                        scheduler_start_called_at=absolute_start_called_at,
                        scheduler_base_time=absolute_base_time,
                        task_create_start_at=task_create_start_at,
                        per_task_created_at=per_task_created_times.get(reader_index),
                        all_tasks_created_at=all_tasks_created_at,
                        task_first_entered_at=first_entered_at,
                        first_run_at=first_run_at,
                        first_scheduled_at=first_scheduled_at,
                        first_sleep_delay_ms=first_sleep_delay_ms,
                        first_sleep_entered_at=first_sleep_entered_at,
                        first_sleep_woke_at=first_sleep_woke_at,
                        first_sleep_wake_lag_ms=first_sleep_wake_lag_ms,
                    )
                )
            actual_start_monotonic: float | None = None
            limiter_wait_start_at = loop.time()
            limiter_acquired_at: float | None = None
            operation_finished_at: float | None = None

            async def operation() -> TickResult:
                nonlocal actual_start_monotonic
                nonlocal limiter_acquired_at
                nonlocal operation_finished_at
                limiter_acquired_at = loop.time()
                actual_start_monotonic = loop.time()
                result = await reader.read_tick(expected_value_count=expected_value_count)
                operation_finished_at = loop.time()
                return result

            try:
                result = await limiter.run(operation)
            except Exception as exc:
                finished_at = loop.time()
                if measure_start_at <= finished_at <= measure_end_at:
                    actual_start = (
                        actual_start_monotonic
                        if actual_start_monotonic is not None
                        else loop.time()
                    )
                    read_finish = time.perf_counter()
                    read_start = read_finish
                    task_count, relevant_task_names = _capture_relevant_task_snapshot(loop)
                    _record_tick(
                        reader_stats[reader_index],
                        TickResult(
                            False,
                            0,
                            0.0,
                            None,
                            read_start,
                            read_finish,
                            type(exc).__name__,
                        ),
                        scheduler_mode="absolute",
                        job_id=f"opcua-reader-{reader_index}",
                        reader_index=reader_index,
                        scheduled_at_monotonic=scheduled_at,
                        actual_start_monotonic=actual_start,
                        diagnostics=PollingTickDiagnostics(
                            scheduled_at=scheduled_at,
                            sleep_woke_at=sleep_woke_at,
                            limiter_wait_start_at=limiter_wait_start_at,
                            limiter_acquired_at=(
                                actual_start if limiter_acquired_at is None else limiter_acquired_at
                            ),
                            operation_start_at=actual_start,
                            operation_finished_at=(
                                finished_at
                                if operation_finished_at is None
                                else operation_finished_at
                            ),
                            callback_enqueue_at=loop.time(),
                            scheduler_mode="absolute",
                            task_name=(
                                asyncio.current_task().get_name()
                                if asyncio.current_task() is not None
                                else None
                            ),
                            scheduler_base_time=base_time,
                            first_run_at=base_time + offset_seconds,
                            offset_seconds=offset_seconds,
                            interval_seconds=interval_seconds,
                            tick_index=tick_index,
                            task_count=task_count if PRINT_SCHEDULER_STRUCTURE else None,
                            relevant_task_names=(
                                relevant_task_names if PRINT_SCHEDULER_STRUCTURE else None
                            ),
                        ),
                    )
                tick_index += 1
                continue

            finished_at = loop.time()
            if measure_start_at <= finished_at <= measure_end_at:
                actual_start = (
                    actual_start_monotonic
                    if actual_start_monotonic is not None
                    else loop.time()
                )
                task_count, relevant_task_names = _capture_relevant_task_snapshot(loop)
                _record_tick(
                    reader_stats[reader_index],
                    result,
                    scheduler_mode="absolute",
                    job_id=f"opcua-reader-{reader_index}",
                    reader_index=reader_index,
                    scheduled_at_monotonic=scheduled_at,
                    actual_start_monotonic=actual_start,
                    diagnostics=PollingTickDiagnostics(
                        scheduled_at=scheduled_at,
                        sleep_woke_at=sleep_woke_at,
                        limiter_wait_start_at=limiter_wait_start_at,
                        limiter_acquired_at=(
                            actual_start if limiter_acquired_at is None else limiter_acquired_at
                        ),
                        operation_start_at=actual_start,
                        operation_finished_at=(
                            finished_at
                            if operation_finished_at is None
                            else operation_finished_at
                        ),
                        callback_enqueue_at=loop.time(),
                        scheduler_mode="absolute",
                        task_name=(
                            asyncio.current_task().get_name()
                            if asyncio.current_task() is not None
                            else None
                        ),
                        scheduler_base_time=base_time,
                        first_run_at=base_time + offset_seconds,
                        offset_seconds=offset_seconds,
                        interval_seconds=interval_seconds,
                        tick_index=tick_index,
                        task_count=task_count if PRINT_SCHEDULER_STRUCTURE else None,
                        relevant_task_names=(
                            relevant_task_names if PRINT_SCHEDULER_STRUCTURE else None
                        ),
                    ),
                )
            tick_index += 1

    tasks: list[asyncio.Task[None]] = []
    for index, reader in enumerate(readers):
        task = asyncio.create_task(
            run_reader(index, reader, offsets[index]),
            name=f"profile-absolute:{index}",
        )
        tasks.append(task)
        per_task_created_times[index] = loop.time()
    all_tasks_created_at = loop.time()
    await asyncio.gather(*tasks)
    return tuple(sorted(task_creation_samples, key=lambda item: item.reader_index))


async def _run_high_frequency_fixed_rate_scheduler(
    *,
    readers: Sequence[OpcUaProfileReader],
    expected_value_count: int,
    interval_seconds: float,
    offsets: Sequence[float],
    limiter: ReadConcurrencyLimiter[TickResult],
    event_sink: Callable[[object], None],
    scheduler_start_at: float,
    measure_start_at: float,
) -> tuple[TaskCreationSample, ...]:
    base_time = (
        measure_start_at
        if ABSOLUTE_BASE_MODE == "measure_start"
        else scheduler_start_at
    )
    scheduler = HighFrequencyFixedRateScheduler[TickResult](
        limiter=limiter,
        base_time=base_time,
    )
    scheduler._event_sink = event_sink  # type: ignore[attr-defined]

    async def on_result(_event: PollingResultEvent[TickResult]) -> None:
        return None

    async def on_error(_event: PollingErrorEvent) -> None:
        return None

    for index, reader in enumerate(readers):

        async def operation(*, reader: OpcUaProfileReader = reader) -> TickResult:
            return await reader.read_tick(expected_value_count=expected_value_count)

        scheduler.add_job(
            PollingJobSpec[TickResult](
                job_id=f"opcua-reader-{index}",
                interval_seconds=interval_seconds,
                offset_seconds=offsets[index],
                timeout_seconds=READ_TIMEOUT_S,
                operation=operation,
                on_result=on_result,
                on_error=on_error,
            )
        )

    await scheduler.start()
    try:
        await asyncio.sleep(WARMUP_S + LOAD_LEVEL_DURATION_S)
    finally:
        await scheduler.stop()

    samples: list[TaskCreationSample] = []
    for diagnostics in scheduler.task_creation_snapshot():
        reader_index = int(diagnostics.job_id.rsplit("-", 1)[-1])
        samples.append(
            TaskCreationSample(
                scheduler_mode="high_frequency_fixed_rate",
                reader_index=reader_index,
                task_name=diagnostics.task_name,
                scheduler_start_called_at=diagnostics.scheduler_start_called_at,
                scheduler_base_time=diagnostics.scheduler_base_time,
                task_create_start_at=diagnostics.task_create_start_at,
                per_task_created_at=diagnostics.per_job_task_created_at,
                all_tasks_created_at=diagnostics.all_tasks_created_at,
                task_first_entered_at=diagnostics.run_job_first_entered_at,
                first_run_at=diagnostics.first_run_at,
                first_scheduled_at=diagnostics.first_scheduled_at,
                first_sleep_delay_ms=diagnostics.first_sleep_delay_ms,
                first_sleep_entered_at=diagnostics.first_sleep_entered_at,
                first_sleep_woke_at=diagnostics.first_sleep_woke_at,
                first_sleep_wake_lag_ms=diagnostics.first_sleep_wake_lag_ms,
            )
        )
    return tuple(sorted(samples, key=lambda item: item.reader_index))


async def _run_high_frequency_central_ticker_scheduler(
    *,
    readers: Sequence[OpcUaProfileReader],
    expected_value_count: int,
    interval_seconds: float,
    offsets: Sequence[float],
    limiter: ReadConcurrencyLimiter[TickResult],
    event_sink: Callable[[object], None],
    scheduler_start_at: float,
    measure_start_at: float,
) -> tuple[TaskCreationSample, ...]:
    loop = asyncio.get_running_loop()
    base_time = (
        measure_start_at
        if ABSOLUTE_BASE_MODE == "measure_start"
        else scheduler_start_at
    )
    stop_after = WARMUP_S + LOAD_LEVEL_DURATION_S
    stop_event = asyncio.Event()
    task_creation_started_at = loop.time()
    task_creation_samples: dict[int, TaskCreationSample] = {}
    worker_tasks: set[asyncio.Task[None]] = set()

    states = [
        {
            "reader_index": index,
            "reader": reader,
            "job_id": f"opcua-reader-{index}",
            "offset_seconds": offsets[index],
            "tick_index": 0,
        }
        for index, reader in enumerate(readers)
    ]

    async def execute_state(state: dict[str, object], scheduled_at: float, tick_index: int) -> None:
        reader_index = int(state["reader_index"])
        reader = state["reader"]
        assert isinstance(reader, OpcUaProfileReader)
        offset_seconds = float(state["offset_seconds"])
        sleep_woke_at = loop.time()
        if reader_index not in task_creation_samples:
            task_creation_samples[reader_index] = TaskCreationSample(
                scheduler_mode="high_frequency_central_ticker",
                reader_index=reader_index,
                task_name=(
                    asyncio.current_task().get_name()
                    if asyncio.current_task() is not None
                    else None
                ),
                scheduler_start_called_at=scheduler_start_at,
                scheduler_base_time=base_time,
                task_create_start_at=task_creation_started_at,
                per_task_created_at=task_creation_started_at,
                all_tasks_created_at=task_creation_started_at,
                task_first_entered_at=task_creation_started_at,
                first_run_at=base_time + offset_seconds,
                first_scheduled_at=base_time + offset_seconds,
                first_sleep_delay_ms=max(0.0, (scheduled_at - base_time) * 1000.0),
                first_sleep_entered_at=base_time,
                first_sleep_woke_at=sleep_woke_at,
                first_sleep_wake_lag_ms=max(0.0, (sleep_woke_at - scheduled_at) * 1000.0),
            )

        limiter_wait_start_at = loop.time()
        limiter_acquired_at: float | None = None
        operation_start_at: float | None = None
        operation_finished_at: float | None = None

        async def run_once() -> TickResult:
            nonlocal limiter_acquired_at
            nonlocal operation_start_at
            nonlocal operation_finished_at
            limiter_acquired_at = loop.time()
            operation_start_at = loop.time()
            try:
                return await reader.read_tick(expected_value_count=expected_value_count)
            finally:
                operation_finished_at = loop.time()

        try:
            result = await limiter.run(run_once)
        except Exception as exc:
            finished_at = loop.time()
            actual_started_at = (
                operation_start_at
                if operation_start_at is not None
                else (
                    limiter_acquired_at
                    if limiter_acquired_at is not None
                    else limiter_wait_start_at
                )
            )
            event_sink(
                PollingErrorEvent(
                    job_id=str(state["job_id"]),
                    scheduled_at=scheduled_at,
                    started_at=actual_started_at,
                    finished_at=finished_at,
                    duration_ms=max(0.0, (finished_at - actual_started_at) * 1000.0),
                    scheduled_delay_ms=max(0.0, (actual_started_at - scheduled_at) * 1000.0),
                    error_type=type(exc).__name__,
                    error_message=str(exc),
                    exception=exc,
                    diagnostics=PollingTickDiagnostics(
                        scheduled_at=scheduled_at,
                        sleep_woke_at=sleep_woke_at,
                        limiter_wait_start_at=limiter_wait_start_at,
                        limiter_acquired_at=(
                            actual_started_at
                            if limiter_acquired_at is None
                            else limiter_acquired_at
                        ),
                        operation_start_at=actual_started_at,
                        operation_finished_at=(
                            finished_at
                            if operation_finished_at is None
                            else operation_finished_at
                        ),
                        callback_enqueue_at=loop.time(),
                        scheduler_mode="high_frequency_central_ticker",
                        task_name=(
                            asyncio.current_task().get_name()
                            if asyncio.current_task() is not None
                            else None
                        ),
                        scheduler_base_time=base_time,
                        first_run_at=base_time + offset_seconds,
                        offset_seconds=offset_seconds,
                        interval_seconds=interval_seconds,
                        tick_index=tick_index,
                    ),
                )
            )
            return

        finished_at = loop.time()
        actual_started_at = (
            operation_start_at
            if operation_start_at is not None
            else (
                limiter_acquired_at
                if limiter_acquired_at is not None
                else limiter_wait_start_at
            )
        )
        event_sink(
            PollingResultEvent(
                job_id=str(state["job_id"]),
                scheduled_at=scheduled_at,
                started_at=actual_started_at,
                finished_at=finished_at,
                duration_ms=max(0.0, (finished_at - actual_started_at) * 1000.0),
                scheduled_delay_ms=max(0.0, (actual_started_at - scheduled_at) * 1000.0),
                result=result,
                diagnostics=PollingTickDiagnostics(
                    scheduled_at=scheduled_at,
                    sleep_woke_at=sleep_woke_at,
                    limiter_wait_start_at=limiter_wait_start_at,
                    limiter_acquired_at=(
                        actual_started_at
                        if limiter_acquired_at is None
                        else limiter_acquired_at
                    ),
                    operation_start_at=actual_started_at,
                    operation_finished_at=(
                        finished_at
                        if operation_finished_at is None
                        else operation_finished_at
                    ),
                    callback_enqueue_at=loop.time(),
                    scheduler_mode="high_frequency_central_ticker",
                    task_name=(
                        asyncio.current_task().get_name()
                        if asyncio.current_task() is not None
                        else None
                    ),
                    scheduler_base_time=base_time,
                    first_run_at=base_time + offset_seconds,
                    offset_seconds=offset_seconds,
                    interval_seconds=interval_seconds,
                    tick_index=tick_index,
                ),
            )
        )

    async def ticker() -> None:
        while not stop_event.is_set():
            next_scheduled_at = min(
                base_time + float(state["offset_seconds"]) + (int(state["tick_index"]) * interval_seconds)
                for state in states
            )
            delay_seconds = next_scheduled_at - loop.time()
            if delay_seconds > 0:
                await asyncio.sleep(delay_seconds)
            now = loop.time()
            due_states = [
                state
                for state in states
                if base_time + float(state["offset_seconds"]) + (int(state["tick_index"]) * interval_seconds)
                <= now
            ]
            for state in due_states:
                tick_index = int(state["tick_index"])
                scheduled_at = (
                    base_time
                    + float(state["offset_seconds"])
                    + (tick_index * interval_seconds)
                )
                state["tick_index"] = tick_index + 1
                task = asyncio.create_task(
                    execute_state(state, scheduled_at, tick_index),
                    name=f"central-ticker-job:{state['job_id']}:{tick_index}",
                )
                worker_tasks.add(task)
                task.add_done_callback(worker_tasks.discard)

    ticker_task = asyncio.create_task(ticker(), name="high-frequency-central-ticker")
    try:
        await asyncio.sleep(stop_after)
    finally:
        stop_event.set()
        ticker_task.cancel()
        await asyncio.gather(ticker_task, return_exceptions=True)
        if worker_tasks:
            for task in tuple(worker_tasks):
                task.cancel()
            await asyncio.gather(*tuple(worker_tasks), return_exceptions=True)

    return tuple(sorted(task_creation_samples.values(), key=lambda item: item.reader_index))


async def _sleep_until_with_yield(
    loop: asyncio.AbstractEventLoop,
    target: float,
) -> float:
    remaining = target - loop.time()
    if remaining > 0.003:
        await asyncio.sleep(max(0.0, remaining - 0.001))
    while True:
        now = loop.time()
        if now >= target:
            return now
        await asyncio.sleep(0)


async def _run_high_frequency_coarse_sleep_spin_scheduler(
    *,
    readers: Sequence[OpcUaProfileReader],
    reader_stats: Sequence[ReaderStats],
    expected_value_count: int,
    interval_seconds: float,
    offsets: Sequence[float],
    limiter: ReadConcurrencyLimiter[TickResult],
    measure_start_at: float,
    measure_end_at: float,
    scheduler_start_at: float,
) -> tuple[TaskCreationSample, ...]:
    loop = asyncio.get_running_loop()
    stop_at = measure_end_at
    absolute_start_called_at = loop.time()
    base_time = (
        measure_start_at
        if ABSOLUTE_BASE_MODE == "measure_start"
        else scheduler_start_at
    )
    task_create_start_at = loop.time()
    task_creation_samples: list[TaskCreationSample] = []
    per_task_created_times: dict[int, float] = {}
    all_tasks_created_at: float | None = None

    async def run_reader(reader_index: int, reader: OpcUaProfileReader, offset_seconds: float) -> None:
        task_name = (
            asyncio.current_task().get_name()
            if asyncio.current_task() is not None
            else None
        )
        first_entered_at = loop.time()
        first_run_at = base_time + offset_seconds
        first_scheduled_at = first_run_at
        tick_index = 0
        first_sleep_delay_ms: float | None = None
        first_sleep_entered_at: float | None = None
        first_sleep_woke_at: float | None = None
        first_sleep_wake_lag_ms: float | None = None

        while True:
            scheduled_at = base_time + offset_seconds + (tick_index * interval_seconds)
            if scheduled_at > stop_at:
                return
            delay_seconds = scheduled_at - loop.time()
            if tick_index == 0:
                first_sleep_delay_ms = max(0.0, delay_seconds * 1000.0)
                first_sleep_entered_at = loop.time()
            sleep_woke_at = await _sleep_until_with_yield(loop, scheduled_at)
            if tick_index == 0:
                first_sleep_woke_at = sleep_woke_at
                first_sleep_wake_lag_ms = max(
                    0.0,
                    (sleep_woke_at - scheduled_at) * 1000.0,
                )
                task_creation_samples.append(
                    TaskCreationSample(
                        scheduler_mode="high_frequency_coarse_sleep_spin",
                        reader_index=reader_index,
                        task_name=task_name,
                        scheduler_start_called_at=absolute_start_called_at,
                        scheduler_base_time=base_time,
                        task_create_start_at=task_create_start_at,
                        per_task_created_at=per_task_created_times.get(reader_index),
                        all_tasks_created_at=all_tasks_created_at,
                        task_first_entered_at=first_entered_at,
                        first_run_at=first_run_at,
                        first_scheduled_at=first_scheduled_at,
                        first_sleep_delay_ms=first_sleep_delay_ms,
                        first_sleep_entered_at=first_sleep_entered_at,
                        first_sleep_woke_at=first_sleep_woke_at,
                        first_sleep_wake_lag_ms=first_sleep_wake_lag_ms,
                    )
                )

            actual_start_monotonic: float | None = None
            limiter_wait_start_at = loop.time()
            limiter_acquired_at: float | None = None
            operation_finished_at: float | None = None

            async def operation() -> TickResult:
                nonlocal actual_start_monotonic
                nonlocal limiter_acquired_at
                nonlocal operation_finished_at
                limiter_acquired_at = loop.time()
                actual_start_monotonic = loop.time()
                result = await reader.read_tick(expected_value_count=expected_value_count)
                operation_finished_at = loop.time()
                return result

            try:
                result = await limiter.run(operation)
            except Exception as exc:
                finished_at = loop.time()
                if measure_start_at <= finished_at <= measure_end_at:
                    actual_start = (
                        actual_start_monotonic
                        if actual_start_monotonic is not None
                        else loop.time()
                    )
                    read_finish = time.perf_counter()
                    read_start = read_finish
                    _record_tick(
                        reader_stats[reader_index],
                        TickResult(
                            False,
                            0,
                            0.0,
                            None,
                            read_start,
                            read_finish,
                            type(exc).__name__,
                        ),
                        scheduler_mode="high_frequency_coarse_sleep_spin",
                        job_id=f"opcua-reader-{reader_index}",
                        reader_index=reader_index,
                        scheduled_at_monotonic=scheduled_at,
                        actual_start_monotonic=actual_start,
                        diagnostics=PollingTickDiagnostics(
                            scheduled_at=scheduled_at,
                            sleep_woke_at=sleep_woke_at,
                            limiter_wait_start_at=limiter_wait_start_at,
                            limiter_acquired_at=(
                                actual_start if limiter_acquired_at is None else limiter_acquired_at
                            ),
                            operation_start_at=actual_start,
                            operation_finished_at=(
                                finished_at
                                if operation_finished_at is None
                                else operation_finished_at
                            ),
                            callback_enqueue_at=loop.time(),
                            scheduler_mode="high_frequency_coarse_sleep_spin",
                            task_name=task_name,
                            scheduler_base_time=base_time,
                            first_run_at=base_time + offset_seconds,
                            offset_seconds=offset_seconds,
                            interval_seconds=interval_seconds,
                            tick_index=tick_index,
                        ),
                    )
                tick_index += 1
                continue

            finished_at = loop.time()
            if measure_start_at <= finished_at <= measure_end_at:
                actual_start = (
                    actual_start_monotonic
                    if actual_start_monotonic is not None
                    else loop.time()
                )
                _record_tick(
                    reader_stats[reader_index],
                    result,
                    scheduler_mode="high_frequency_coarse_sleep_spin",
                    job_id=f"opcua-reader-{reader_index}",
                    reader_index=reader_index,
                    scheduled_at_monotonic=scheduled_at,
                    actual_start_monotonic=actual_start,
                    diagnostics=PollingTickDiagnostics(
                        scheduled_at=scheduled_at,
                        sleep_woke_at=sleep_woke_at,
                        limiter_wait_start_at=limiter_wait_start_at,
                        limiter_acquired_at=(
                            actual_start if limiter_acquired_at is None else limiter_acquired_at
                        ),
                        operation_start_at=actual_start,
                        operation_finished_at=(
                            finished_at
                            if operation_finished_at is None
                            else operation_finished_at
                        ),
                        callback_enqueue_at=loop.time(),
                        scheduler_mode="high_frequency_coarse_sleep_spin",
                        task_name=task_name,
                        scheduler_base_time=base_time,
                        first_run_at=base_time + offset_seconds,
                        offset_seconds=offset_seconds,
                        interval_seconds=interval_seconds,
                        tick_index=tick_index,
                    ),
                )
            tick_index += 1

    tasks: list[asyncio.Task[None]] = []
    for index, reader in enumerate(readers):
        task = asyncio.create_task(
            run_reader(index, reader, offsets[index]),
            name=f"profile-coarse-sleep-spin:{index}",
        )
        tasks.append(task)
        per_task_created_times[index] = loop.time()
    all_tasks_created_at = loop.time()
    await asyncio.gather(*tasks)
    return tuple(sorted(task_creation_samples, key=lambda item: item.reader_index))


async def _run_open62541_runner_poll_mode(
    *,
    readers: Sequence[OpcUaProfileReader],
    reader_stats: Sequence[ReaderStats],
    expected_value_count: int,
) -> tuple[TaskCreationSample, ...]:
    """Run fixed-rate polling inside the open62541 C runner."""

    async def consume_reader(reader_index: int, reader: OpcUaProfileReader) -> None:
        ticks = await reader.stream_runner_poll(
            expected_value_count=expected_value_count,
            target_hz=TARGET_HZ,
            warmup_s=WARMUP_S,
            duration_s=LOAD_LEVEL_DURATION_S,
        )
        if not ticks:
            return

        first_scheduled_ns = ticks[0].runner_scheduled_ts_ns
        if first_scheduled_ns is None:
            raise RuntimeError("open62541 runner poll stream is missing scheduled timestamps")

        warmup_end_ns = first_scheduled_ns + int(WARMUP_S * 1_000_000_000.0)
        measure_end_ns = warmup_end_ns + int(LOAD_LEVEL_DURATION_S * 1_000_000_000.0)
        target_period_s = 1.0 / TARGET_HZ

        for tick in ticks:
            scheduled_ns = tick.runner_scheduled_ts_ns
            if scheduled_ns is None:
                continue
            if scheduled_ns < warmup_end_ns or scheduled_ns >= measure_end_ns:
                continue

            scheduled_at = scheduled_ns / 1_000_000_000.0
            actual_start_at = (
                tick.runner_read_start_ts_ns / 1_000_000_000.0
                if tick.runner_read_start_ts_ns is not None
                else scheduled_at
            )
            callback_enqueue_at = (
                tick.stdout_line_received_ts_ns / 1_000_000_000.0
                if tick.stdout_line_received_ts_ns is not None
                else tick.read_finish_monotonic
            )
            seq_index = int(
                round(
                    (scheduled_ns - first_scheduled_ns)
                    / (target_period_s * 1_000_000_000.0)
                )
            )
            _record_tick(
                reader_stats[reader_index],
                tick,
                scheduler_mode="open62541_runner_poll",
                job_id=f"opcua-runner-poll-{reader_index}",
                reader_index=reader_index,
                scheduled_at_monotonic=scheduled_at,
                actual_start_monotonic=actual_start_at,
                diagnostics=PollingTickDiagnostics(
                    scheduled_at=scheduled_at,
                    sleep_woke_at=scheduled_at,
                    limiter_wait_start_at=scheduled_at,
                    limiter_acquired_at=actual_start_at,
                    operation_start_at=actual_start_at,
                    operation_finished_at=tick.read_finish_monotonic,
                    callback_enqueue_at=callback_enqueue_at,
                    scheduler_mode="open62541_runner_poll",
                    task_name=None,
                    scheduler_base_time=first_scheduled_ns / 1_000_000_000.0,
                    first_run_at=first_scheduled_ns / 1_000_000_000.0,
                    offset_seconds=0.0,
                    interval_seconds=target_period_s,
                    tick_index=seq_index,
                ),
            )

    await asyncio.gather(
        *(consume_reader(reader_index, reader) for reader_index, reader in enumerate(readers))
    )
    return ()


async def _run_high_frequency_grouped_reader_loop_scheduler(
    *,
    readers: Sequence[OpcUaProfileReader],
    expected_value_count: int,
    interval_seconds: float,
    offsets: Sequence[float],
    limiter: ReadConcurrencyLimiter[TickResult],
    event_sink: Callable[[object], None],
    scheduler_start_at: float,
    measure_start_at: float,
) -> tuple[TaskCreationSample, ...]:
    loop = asyncio.get_running_loop()
    base_time = (
        measure_start_at
        if ABSOLUTE_BASE_MODE == "measure_start"
        else scheduler_start_at
    )
    stop_event = asyncio.Event()
    stop_after = WARMUP_S + LOAD_LEVEL_DURATION_S
    group_count = max(1, min(SCHEDULER_GROUP_COUNT, len(readers)))
    worker_tasks: set[asyncio.Task[None]] = set()
    task_creation_samples: dict[int, TaskCreationSample] = {}
    task_create_start_at = loop.time()

    groups: list[list[dict[str, object]]] = [[] for _ in range(group_count)]
    for index, reader in enumerate(readers):
        groups[index % group_count].append(
            {
                "reader_index": index,
                "reader": reader,
                "job_id": f"opcua-reader-{index}",
                "offset_seconds": offsets[index],
                "tick_index": 0,
            }
        )

    async def execute_state(
        *,
        state: dict[str, object],
        scheduled_at: float,
        tick_index: int,
        task_name: str,
    ) -> None:
        reader_index = int(state["reader_index"])
        reader = state["reader"]
        assert isinstance(reader, OpcUaProfileReader)
        offset_seconds = float(state["offset_seconds"])
        sleep_woke_at = loop.time()
        if reader_index not in task_creation_samples:
            task_creation_samples[reader_index] = TaskCreationSample(
                scheduler_mode="high_frequency_grouped_reader_loop",
                reader_index=reader_index,
                task_name=task_name,
                scheduler_start_called_at=scheduler_start_at,
                scheduler_base_time=base_time,
                task_create_start_at=task_create_start_at,
                per_task_created_at=task_create_start_at,
                all_tasks_created_at=task_create_start_at,
                task_first_entered_at=task_create_start_at,
                first_run_at=base_time + offset_seconds,
                first_scheduled_at=base_time + offset_seconds,
                first_sleep_delay_ms=max(0.0, (scheduled_at - base_time) * 1000.0),
                first_sleep_entered_at=base_time,
                first_sleep_woke_at=sleep_woke_at,
                first_sleep_wake_lag_ms=max(0.0, (sleep_woke_at - scheduled_at) * 1000.0),
            )

        limiter_wait_start_at = loop.time()
        limiter_acquired_at: float | None = None
        operation_start_at: float | None = None
        operation_finished_at: float | None = None

        async def run_once() -> TickResult:
            nonlocal limiter_acquired_at
            nonlocal operation_start_at
            nonlocal operation_finished_at
            limiter_acquired_at = loop.time()
            operation_start_at = loop.time()
            try:
                return await reader.read_tick(expected_value_count=expected_value_count)
            finally:
                operation_finished_at = loop.time()

        try:
            result = await limiter.run(run_once)
        except Exception as exc:
            finished_at = loop.time()
            actual_started_at = (
                operation_start_at
                if operation_start_at is not None
                else (
                    limiter_acquired_at
                    if limiter_acquired_at is not None
                    else limiter_wait_start_at
                )
            )
            event_sink(
                PollingErrorEvent(
                    job_id=str(state["job_id"]),
                    scheduled_at=scheduled_at,
                    started_at=actual_started_at,
                    finished_at=finished_at,
                    duration_ms=max(0.0, (finished_at - actual_started_at) * 1000.0),
                    scheduled_delay_ms=max(0.0, (actual_started_at - scheduled_at) * 1000.0),
                    error_type=type(exc).__name__,
                    error_message=str(exc),
                    exception=exc,
                    diagnostics=PollingTickDiagnostics(
                        scheduled_at=scheduled_at,
                        sleep_woke_at=sleep_woke_at,
                        limiter_wait_start_at=limiter_wait_start_at,
                        limiter_acquired_at=(
                            actual_started_at
                            if limiter_acquired_at is None
                            else limiter_acquired_at
                        ),
                        operation_start_at=actual_started_at,
                        operation_finished_at=(
                            finished_at
                            if operation_finished_at is None
                            else operation_finished_at
                        ),
                        callback_enqueue_at=loop.time(),
                        scheduler_mode="high_frequency_grouped_reader_loop",
                        task_name=task_name,
                        scheduler_base_time=base_time,
                        first_run_at=base_time + offset_seconds,
                        offset_seconds=offset_seconds,
                        interval_seconds=interval_seconds,
                        tick_index=tick_index,
                    ),
                )
            )
            return

        finished_at = loop.time()
        actual_started_at = (
            operation_start_at
            if operation_start_at is not None
            else (
                limiter_acquired_at
                if limiter_acquired_at is not None
                else limiter_wait_start_at
            )
        )
        event_sink(
            PollingResultEvent(
                job_id=str(state["job_id"]),
                scheduled_at=scheduled_at,
                started_at=actual_started_at,
                finished_at=finished_at,
                duration_ms=max(0.0, (finished_at - actual_started_at) * 1000.0),
                scheduled_delay_ms=max(0.0, (actual_started_at - scheduled_at) * 1000.0),
                result=result,
                diagnostics=PollingTickDiagnostics(
                    scheduled_at=scheduled_at,
                    sleep_woke_at=sleep_woke_at,
                    limiter_wait_start_at=limiter_wait_start_at,
                    limiter_acquired_at=(
                        actual_started_at
                        if limiter_acquired_at is None
                        else limiter_acquired_at
                    ),
                    operation_start_at=actual_started_at,
                    operation_finished_at=(
                        finished_at
                        if operation_finished_at is None
                        else operation_finished_at
                    ),
                    callback_enqueue_at=loop.time(),
                    scheduler_mode="high_frequency_grouped_reader_loop",
                    task_name=task_name,
                    scheduler_base_time=base_time,
                    first_run_at=base_time + offset_seconds,
                    offset_seconds=offset_seconds,
                    interval_seconds=interval_seconds,
                    tick_index=tick_index,
                ),
            )
        )

    async def run_group(group_index: int, states: list[dict[str, object]]) -> None:
        task_name = f"grouped-reader-loop:{group_index}"
        while not stop_event.is_set():
            next_scheduled_at = min(
                base_time + float(state["offset_seconds"]) + (int(state["tick_index"]) * interval_seconds)
                for state in states
            )
            delay_seconds = next_scheduled_at - loop.time()
            if delay_seconds > 0:
                await asyncio.sleep(delay_seconds)
            now = loop.time()
            due_states = [
                state
                for state in states
                if base_time + float(state["offset_seconds"]) + (int(state["tick_index"]) * interval_seconds)
                <= now
            ]
            for state in due_states:
                tick_index = int(state["tick_index"])
                scheduled_at = (
                    base_time
                    + float(state["offset_seconds"])
                    + (tick_index * interval_seconds)
                )
                state["tick_index"] = tick_index + 1
                task = asyncio.create_task(
                    execute_state(
                        state=state,
                        scheduled_at=scheduled_at,
                        tick_index=tick_index,
                        task_name=task_name,
                    ),
                    name=f"{task_name}:{state['job_id']}:{tick_index}",
                )
                worker_tasks.add(task)
                task.add_done_callback(worker_tasks.discard)

    group_tasks = [
        asyncio.create_task(run_group(index, group), name=f"grouped-reader-loop:{index}")
        for index, group in enumerate(groups)
    ]
    try:
        await asyncio.sleep(stop_after)
    finally:
        stop_event.set()
        for task in group_tasks:
            task.cancel()
        await asyncio.gather(*group_tasks, return_exceptions=True)
        if worker_tasks:
            for task in tuple(worker_tasks):
                task.cancel()
            await asyncio.gather(*tuple(worker_tasks), return_exceptions=True)

    return tuple(sorted(task_creation_samples.values(), key=lambda item: item.reader_index))


def _record_tick(
    stats: ReaderStats,
    result: TickResult,
    *,
    scheduler_mode: str,
    job_id: str,
    reader_index: int,
    scheduled_at_monotonic: float,
    actual_start_monotonic: float,
    diagnostics: PollingTickDiagnostics | None = None,
) -> None:
    stats.total_reads += 1
    stats.tick_ms_values.append(result.elapsed_ms)
    stats.tick_samples.append(
        TickSample(
            scheduler_mode=(
                diagnostics.scheduler_mode
                if diagnostics is not None and diagnostics.scheduler_mode is not None
                else scheduler_mode
            ),
            task_name=diagnostics.task_name if diagnostics is not None else None,
            job_id=job_id,
            reader_index=reader_index,
            tick_index=(
                diagnostics.tick_index
                if diagnostics is not None and diagnostics.tick_index is not None
                else stats.total_reads - 1
            ),
            scheduler_base_time=(
                diagnostics.scheduler_base_time if diagnostics is not None else None
            ),
            first_run_at=diagnostics.first_run_at if diagnostics is not None else None,
            offset_seconds=(
                diagnostics.offset_seconds if diagnostics is not None else None
            ),
            interval_seconds=(
                diagnostics.interval_seconds if diagnostics is not None else None
            ),
            scheduled_at_monotonic=scheduled_at_monotonic,
            actual_start_monotonic=actual_start_monotonic,
            read_start_monotonic=result.read_start_monotonic,
            read_finish_monotonic=result.read_finish_monotonic,
            response_timestamp_s=result.response_timestamp_s,
            value_count=result.value_count,
            error=result.error,
            **_sample_diagnostics_kwargs(diagnostics),
            command_write_ts_ns=result.command_write_ts_ns,
            command_drain_done_ts_ns=result.command_drain_done_ts_ns,
            stdout_line_received_ts_ns=result.stdout_line_received_ts_ns,
            runner_request_received_ts_ns=result.runner_request_received_ts_ns,
            runner_scheduled_ts_ns=result.runner_scheduled_ts_ns,
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
                        previous_schedule_lag_ms=previous.schedule_lag_ms,
                        current_schedule_lag_ms=current.schedule_lag_ms,
                        schedule_gap_ms=(
                            current.actual_start_monotonic - previous.actual_start_monotonic
                        )
                        * 1000.0,
                        previous_sleep_wake_lag_ms=previous.sleep_wake_lag_ms,
                        current_sleep_wake_lag_ms=current.sleep_wake_lag_ms,
                        previous_limiter_wait_ms=previous.limiter_wait_ms,
                        current_limiter_wait_ms=current.limiter_wait_ms,
                        previous_pre_operation_overhead_ms=previous.pre_operation_overhead_ms,
                        current_pre_operation_overhead_ms=current.pre_operation_overhead_ms,
                        previous_operation_ms=previous.operation_ms,
                        current_operation_ms=current.operation_ms,
                        previous_callback_enqueue_ms=previous.callback_enqueue_ms,
                        current_callback_enqueue_ms=current.callback_enqueue_ms,
                        c_scheduled_period_ms=_optional_gap_ms(
                            current.runner_scheduled_ts_ns,
                            previous.runner_scheduled_ts_ns,
                        ),
                        c_read_start_period_ms=_optional_gap_ms(
                            current.runner_read_start_ts_ns,
                            previous.runner_read_start_ts_ns,
                        ),
                        c_read_end_period_ms=_optional_gap_ms(
                            current.runner_read_end_ts_ns,
                            previous.runner_read_end_ts_ns,
                        ),
                        py_stdout_period_ms=_optional_gap_ms(
                            current.stdout_line_received_ts_ns,
                            previous.stdout_line_received_ts_ns,
                        ),
                        runner_read_ms=_optional_duration_ms(
                            current.runner_read_end_ts_ns, current.runner_read_start_ts_ns
                        ),
                        pipe_back_ms=_optional_duration_ms(
                            current.stdout_line_received_ts_ns,
                            current.runner_response_write_ts_ns,
                        ),
                        c_response_write_period_ms=_optional_gap_ms(
                            current.runner_response_write_ts_ns,
                            previous.runner_response_write_ts_ns,
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


def _max_optional(values: Sequence[float | None]) -> float | None:
    present = [value for value in values if value is not None]
    if not present:
        return None
    return max(present)


def _classify_gap(
    gap: PeriodGap,
    *,
    allowed_period_max_ms: float,
) -> GapClassification:
    checks = {
        "c_schedule_spike": gap.c_scheduled_period_ms,
        "c_read_start_spike": gap.c_read_start_period_ms,
        "c_response_write_spike": gap.c_response_write_period_ms,
        "python_receive_spike": gap.py_stdout_period_ms,
        "response_timestamp_only_spike": gap.response_period_ms,
    }
    exceeded = {
        name: value
        for name, value in checks.items()
        if value is not None and value >= allowed_period_max_ms
    }

    if len(exceeded) >= 2:
        return "mixed_spike"
    if (
        gap.c_scheduled_period_ms is not None
        and gap.c_scheduled_period_ms >= allowed_period_max_ms
    ):
        return "c_schedule_spike"
    if (
        gap.c_read_start_period_ms is not None
        and gap.c_read_start_period_ms >= allowed_period_max_ms
    ):
        return "c_read_start_spike"
    if (
        gap.c_response_write_period_ms is not None
        and gap.c_response_write_period_ms >= allowed_period_max_ms
    ):
        return "c_response_write_spike"
    if (
        gap.py_stdout_period_ms is not None
        and gap.py_stdout_period_ms >= allowed_period_max_ms
        and (
            gap.c_response_write_period_ms is None
            or gap.c_response_write_period_ms < allowed_period_max_ms
        )
    ):
        return "python_receive_spike"
    if (
        (gap.c_response_write_period_ms is None or gap.c_response_write_period_ms < allowed_period_max_ms)
        and (gap.py_stdout_period_ms is None or gap.py_stdout_period_ms < allowed_period_max_ms)
        and gap.response_period_ms >= allowed_period_max_ms
    ):
        return "response_timestamp_only_spike"
    return "unknown"


def _build_period_decomposition_summary(
    top_gaps: Sequence[PeriodGap],
    *,
    allowed_period_max_ms: float,
) -> PeriodDecompositionSummary:
    classified_top_gaps = tuple(
        ClassifiedPeriodGap(
            gap=gap,
            classification=_classify_gap(
                gap,
                allowed_period_max_ms=allowed_period_max_ms,
            ),
        )
        for gap in top_gaps
    )
    counts = {
        "c_schedule_spike": 0,
        "c_read_start_spike": 0,
        "python_receive_spike": 0,
        "c_response_write_spike": 0,
        "response_timestamp_only_spike": 0,
        "mixed_spike": 0,
        "unknown": 0,
    }
    for item in classified_top_gaps:
        counts[item.classification] += 1

    return PeriodDecompositionSummary(
        gap_classification_summary=GapClassificationSummary(**counts),
        max_c_scheduled_period_ms=_max_optional(
            [gap.c_scheduled_period_ms for gap in top_gaps]
        ),
        max_c_read_start_period_ms=_max_optional(
            [gap.c_read_start_period_ms for gap in top_gaps]
        ),
        max_c_read_end_period_ms=_max_optional(
            [gap.c_read_end_period_ms for gap in top_gaps]
        ),
        max_c_response_write_period_ms=_max_optional(
            [gap.c_response_write_period_ms for gap in top_gaps]
        ),
        max_py_stdout_period_ms=_max_optional(
            [gap.py_stdout_period_ms for gap in top_gaps]
        ),
        max_response_period_ms=_max_optional([gap.response_period_ms for gap in top_gaps]),
        max_runner_read_ms=_max_optional([gap.runner_read_ms for gap in top_gaps]),
        max_pipe_back_ms=_max_optional([gap.pipe_back_ms for gap in top_gaps]),
        classified_top_gaps=classified_top_gaps,
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
    period_decomposition = _build_period_decomposition_summary(
        period_stats.top_gaps,
        allowed_period_max_ms=allowed_period_max_ms,
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
        use_uvloop=USE_UVLOOP,
        scheduler_mode=SCHEDULER_MODE,
        scheduler_callback_mode=SCHEDULER_CALLBACK_MODE,
        scheduler_loop_mode=SCHEDULER_LOOP_MODE,
        scheduler_start_mode=SCHEDULER_START_MODE,
        absolute_base=ABSOLUTE_BASE_MODE,
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
        period_decomposition=period_decomposition,
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
    print(f"use_uvloop={metrics.use_uvloop}")
    print(f"scheduler_mode={metrics.scheduler_mode}")
    print(f"scheduler_callback_mode={metrics.scheduler_callback_mode}")
    print(f"scheduler_execution_mode={SCHEDULER_EXECUTION_MODE}")
    print(f"scheduler_loop_mode={metrics.scheduler_loop_mode}")
    print(f"scheduler_start_mode={metrics.scheduler_start_mode}")
    print(f"scheduler_impl={SCHEDULER_IMPL}")
    print(f"absolute_base={metrics.absolute_base}")
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
    decomposition = metrics.period_decomposition
    print("-" * 88)
    print("period decomposition summary:")
    print(
        "max_c_scheduled_period_ms="
        f"{_format_optional_ms(decomposition.max_c_scheduled_period_ms, width=0).strip()}"
    )
    print(
        "max_c_read_start_period_ms="
        f"{_format_optional_ms(decomposition.max_c_read_start_period_ms, width=0).strip()}"
    )
    print(
        "max_c_read_end_period_ms="
        f"{_format_optional_ms(decomposition.max_c_read_end_period_ms, width=0).strip()}"
    )
    print(
        "max_c_response_write_period_ms="
        f"{_format_optional_ms(decomposition.max_c_response_write_period_ms, width=0).strip()}"
    )
    print(
        "max_py_stdout_period_ms="
        f"{_format_optional_ms(decomposition.max_py_stdout_period_ms, width=0).strip()}"
    )
    print(
        f"max_response_period_ms={_format_optional_ms(decomposition.max_response_period_ms, width=0).strip()}"
    )
    print(
        f"max_runner_read_ms={_format_optional_ms(decomposition.max_runner_read_ms, width=0).strip()}"
    )
    print(
        f"max_pipe_back_ms={_format_optional_ms(decomposition.max_pipe_back_ms, width=0).strip()}"
    )
    print("gap_classification_summary:")
    print(
        "  c_schedule_spike="
        f"{decomposition.gap_classification_summary.c_schedule_spike}"
    )
    print(
        "  c_read_start_spike="
        f"{decomposition.gap_classification_summary.c_read_start_spike}"
    )
    print(
        "  python_receive_spike="
        f"{decomposition.gap_classification_summary.python_receive_spike}"
    )
    print(
        "  c_response_write_spike="
        f"{decomposition.gap_classification_summary.c_response_write_spike}"
    )
    print(
        "  response_timestamp_only_spike="
        f"{decomposition.gap_classification_summary.response_timestamp_only_spike}"
    )
    print(f"  mixed_spike={decomposition.gap_classification_summary.mixed_spike}")
    print(f"  unknown={decomposition.gap_classification_summary.unknown}")
    print("=" * 88)


def _format_relative_to_base(
    value: float | None,
    base_time: float | None,
) -> str:
    if value is None or base_time is None:
        return "-"
    return f"{value - base_time:.6f}"


def _print_task_creation_summary(
    task_creation_samples: Sequence[TaskCreationSample],
) -> None:
    if not PRINT_TASK_CREATION or not task_creation_samples:
        return

    print("task creation summary:")
    print(
        "  reader  task_name  task_created_minus_base_s  "
        "task_first_entered_minus_base_s  first_run_minus_base_s  "
        "first_sleep_entered_minus_base_s  first_sleep_delay_ms  "
        "first_sleep_wake_lag_ms"
    )
    for sample in sorted(task_creation_samples, key=lambda item: item.reader_index):
        print(
            f"  {sample.reader_index:>6} "
            f"{(sample.task_name or '-'):>22} "
            f"{_format_relative_to_base(sample.per_task_created_at, sample.scheduler_base_time):>27} "
            f"{_format_relative_to_base(sample.task_first_entered_at, sample.scheduler_base_time):>31} "
            f"{_format_relative_to_base(sample.first_run_at, sample.scheduler_base_time):>22} "
            f"{_format_relative_to_base(sample.first_sleep_entered_at, sample.scheduler_base_time):>32} "
            f"{_format_optional_ms(sample.first_sleep_delay_ms, width=20)} "
            f"{_format_optional_ms(sample.first_sleep_wake_lag_ms, width=24)}"
        )
    print("=" * 88)


def _print_top_gaps(metrics: LevelMetrics) -> None:
    if not metrics.period_decomposition.classified_top_gaps:
        return
    print("top response period gaps:")
    print(
        "  reader  gap  classification  response_period_ms  c_scheduled_period_ms  "
        "c_read_start_period_ms  c_read_end_period_ms  c_response_write_period_ms  "
        "py_stdout_period_ms  runner_read_ms  pipe_back_ms"
    )
    for item in metrics.period_decomposition.classified_top_gaps:
        gap = item.gap
        print(
            f"  {gap.reader_index:>6} {gap.gap_index:>4} "
            f"{item.classification:>28} "
            f"{gap.period_ms:>10.1f} "
            f"{_format_optional_ms(gap.c_scheduled_period_ms, width=21)} "
            f"{_format_optional_ms(gap.c_read_start_period_ms, width=22)} "
            f"{_format_optional_ms(gap.c_read_end_period_ms, width=20)} "
            f"{_format_optional_ms(gap.c_response_write_period_ms, width=27)} "
            f"{_format_optional_ms(gap.py_stdout_period_ms, width=19)} "
            f"{_format_optional_ms(gap.runner_read_ms, width=14)} "
            f"{_format_optional_ms(gap.pipe_back_ms, width=12)}"
        )
    print("=" * 88)


def _find_gap_samples(
    tick_samples_by_reader: Sequence[Sequence[TickSample]],
    gap: PeriodGap,
) -> tuple[TickSample, TickSample] | None:
    comparable_samples = [
        item
        for item in tick_samples_by_reader[gap.reader_index]
        if item.response_timestamp_s is not None
    ]
    if gap.gap_index + 1 >= len(comparable_samples):
        return None
    return comparable_samples[gap.gap_index], comparable_samples[gap.gap_index + 1]


def _print_scheduler_structure_samples(
    metrics: LevelMetrics,
    tick_samples_by_reader: Sequence[Sequence[TickSample]],
) -> None:
    if not PRINT_SCHEDULER_STRUCTURE or not metrics.top_gaps:
        return

    def print_sample(label: str, gap: PeriodGap, sample: TickSample) -> None:
        print(f"reader={gap.reader_index} gap={gap.period_ms:.1f} {label}:")
        print(f"  scheduler_mode={sample.scheduler_mode}")
        print(f"  task_name={sample.task_name}")
        print(f"  job_id={sample.job_id}")
        print(f"  reader_index={sample.reader_index}")
        print(f"  tick_index={sample.tick_index}")
        print(f"  scheduler_base_time={sample.scheduler_base_time}")
        print(f"  first_run_at={sample.first_run_at}")
        print(f"  offset_seconds={sample.offset_seconds}")
        print(f"  interval_seconds={sample.interval_seconds}")
        print(f"  scheduled_at={sample.scheduled_at_monotonic}")
        print(f"  sleep_woke_at={sample.sleep_woke_at_monotonic}")
        print(f"  sleep_wake_lag_ms={sample.sleep_wake_lag_ms}")
        print(f"  actual_start_monotonic={sample.actual_start_monotonic}")
        print(f"  limiter_wait_start_at={sample.limiter_wait_start_at_monotonic}")
        print(f"  limiter_acquired_at={sample.limiter_acquired_at_monotonic}")
        print(f"  operation_start_at={sample.operation_start_at_monotonic}")
        print(f"  operation_finished_at={sample.operation_finished_at_monotonic}")
        print(f"  callback_enqueue_at={sample.callback_enqueue_at_monotonic}")
        print(f"  task_count={sample.task_count}")
        print(f"  relevant_task_names={list(sample.relevant_task_names or ())}")

    print("scheduler structure samples:")
    print()
    for gap in metrics.top_gaps:
        samples = _find_gap_samples(tick_samples_by_reader, gap)
        if samples is None:
            continue
        previous, current = samples
        print_sample("prev", gap, previous)
        print_sample("cur", gap, current)
        print()
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
    if USE_UVLOOP:
        try:
            import uvloop
        except ImportError:  # pragma: no cover - optional dependency
            pytest.skip("uvloop is not installed")
        else:
            uvloop.install()

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
                run_result = asyncio.run(_run_profile_level(sources))
            finally:
                profiler.stop()
        else:
            run_result = asyncio.run(_run_profile_level(sources))

    metrics = run_result.metrics

    profile = _format_profiler_report(profiler)
    diagnosis = _build_diagnosis(metrics, profile)

    _print_metrics(metrics)
    _print_task_creation_summary(run_result.task_creation_samples)
    _print_top_gaps(metrics)
    _print_scheduler_structure_samples(metrics, run_result.tick_samples_by_reader)
    _print_diagnosis(diagnosis)
    _print_profiler_report(profile)
    assert metrics.period_samples >= 0
