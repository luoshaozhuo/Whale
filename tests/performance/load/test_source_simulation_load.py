"""Load test for source simulator sampling capacity.

Goal:
- Keep CPU usage under a configurable limit (default 50%).
- Fix per-server variable count (default 400).
- For each server-count level, find the max sustainable sampling rate when client reads
  full variable set in smooth polling loops.
- Pass criteria per level:
  1) each poll batch size equals fixed variable count;
  2) server_timestamp-derived receive period is close to target sampling period;
  3) CPU peak stays below configured limit.

Run examples:
    SOURCE_SIM_LOAD_LEVEL_DURATION_S=4 \
    SOURCE_SIM_LOAD_SERVER_RAMP=1,2,4 \
    SOURCE_SIM_LOAD_SAMPLE_HZ_RAMP=2,4,6,8,10,12 \
    pytest -q tests/performance/load/test_source_simulation_load.py -s
"""

from __future__ import annotations

import asyncio
import os
import statistics
import sys
import time
from collections import defaultdict
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parents[3]
_SRC_ROOT = _PROJECT_ROOT / "src"
for _path in (str(_PROJECT_ROOT), str(_SRC_ROOT)):
    if _path not in sys.path:
        sys.path.insert(0, _path)

import pytest

from whale.ingest.adapters.config.source_runtime_config_repository import (
    SourceRuntimeConfigRepository,
)
from whale.shared.utils.time import ensure_utc
from tools.source_simulation.adapters.opcua.nodeset_builder import logical_path
from tools.source_simulation.adapters.registry import build_source_reader
from tools.source_simulation.domain import (
    SimulatedPoint,
    SimulatedSource,
    SourceConnection,
    SourceReadPoint,
    UpdateConfig,
)
from tools.source_simulation.fleet import SourceSimulatorFleet

LOAD_LEVEL_DURATION_S = float(os.environ.get("SOURCE_SIM_LOAD_LEVEL_DURATION_S", "5"))
WARMUP_S = float(os.environ.get("SOURCE_SIM_LOAD_WARMUP_S", "1"))
MEASURE_AFTER_S = float(os.environ.get("SOURCE_SIM_LOAD_MEASURE_AFTER_S", "1"))
VARIABLES_PER_SERVER = int(os.environ.get("SOURCE_SIM_LOAD_VARIABLES_PER_SERVER", "400"))
CPU_LIMIT_PERCENT = float(os.environ.get("SOURCE_SIM_LOAD_CPU_LIMIT_PERCENT", "50"))
PERIOD_TOLERANCE_RATIO = float(
    os.environ.get("SOURCE_SIM_LOAD_PERIOD_TOLERANCE_RATIO", "0.2")
)
PERIOD_PASS_RATIO = float(os.environ.get("SOURCE_SIM_LOAD_PERIOD_PASS_RATIO", "0.95"))
MIN_PERIOD_SAMPLES = int(os.environ.get("SOURCE_SIM_LOAD_MIN_PERIOD_SAMPLES", "8"))
SOURCE_UPDATE_HZ = float(os.environ.get("SOURCE_SIM_LOAD_SOURCE_UPDATE_HZ", "10"))
SOURCE_UPDATE_INTERVAL_S = 1.0 / SOURCE_UPDATE_HZ
STAGGER_MODE = os.environ.get("SOURCE_SIM_LOAD_STAGGER_MODE", "even").strip().lower()
SERVER_RAMP = tuple(
    int(part.strip())
    for part in os.environ.get("SOURCE_SIM_LOAD_SERVER_RAMP", "1,2,4,8").split(",")
    if part.strip()
)
SAMPLE_HZ_RAMP = tuple(
    float(part.strip())
    for part in os.environ.get("SOURCE_SIM_LOAD_SAMPLE_HZ_RAMP", "2,4,6,8,10,12").split(",")
    if part.strip()
)
OUTPUT_DIR = Path(os.environ.get("SOURCE_SIM_LOAD_OUTPUT_DIR", "tests/tmp"))
REPORT_PATH = OUTPUT_DIR / "source_simulation_load_report.md"

if STAGGER_MODE not in {"none", "even"}:
    raise ValueError(f"Unsupported SOURCE_SIM_LOAD_STAGGER_MODE: {STAGGER_MODE!r}")

if not SERVER_RAMP:
    raise ValueError("SOURCE_SIM_LOAD_SERVER_RAMP must not be empty")

if not SAMPLE_HZ_RAMP:
    raise ValueError("SOURCE_SIM_LOAD_SAMPLE_HZ_RAMP must not be empty")


@dataclass(frozen=True, slots=True)
class WorkerMetrics:
    """Polling metrics for one server in one level."""

    completed_polls: int
    batch_mismatches: int
    read_errors: int
    achieved_hz: float
    period_sample_count: int
    period_pass_count: int
    period_p95_error_ms: float


@dataclass(frozen=True, slots=True)
class LevelResult:
    """Merged result for one (server_count, target_hz) level."""

    server_count: int
    target_hz: float
    expected_variable_count: int
    completed_polls_total: int
    batch_mismatches_total: int
    read_errors_total: int
    achieved_hz_min: float
    achieved_hz_mean: float
    period_samples_total: int
    period_pass_ratio: float
    period_p95_error_ms: float
    cpu_mean_percent: float
    cpu_peak_percent: float
    passed: bool


@dataclass(frozen=True, slots=True)
class ServerRampSummary:
    """Summary for one server-count ramp."""

    server_count: int
    max_pass_hz: float | None
    levels: tuple[LevelResult, ...]


@dataclass(frozen=True, slots=True)
class LoadTestContext:
    """Shared simulator context for the whole ramp test."""

    servers: tuple[SimulatedSource, ...]
    expected_variable_count: int


def _read_cpu_stat() -> tuple[int, int]:
    """Return (total, idle) ticks from /proc/stat."""

    with open("/proc/stat", "r", encoding="utf-8") as fp:
        parts = fp.readline().split()

    if len(parts) < 8 or parts[0] != "cpu":
        raise RuntimeError("Unexpected /proc/stat format")

    values = [int(item) for item in parts[1:]]
    idle = values[3] + values[4]
    total = sum(values)
    return total, idle


async def _sample_cpu_percent(
    stop_event: asyncio.Event,
    *,
    interval_s: float = 0.25,
) -> list[float]:
    """Sample host CPU usage until stop_event is set."""

    samples: list[float] = []
    prev_total, prev_idle = _read_cpu_stat()

    while not stop_event.is_set():
        await asyncio.sleep(interval_s)
        cur_total, cur_idle = _read_cpu_stat()
        delta_total = cur_total - prev_total
        delta_idle = cur_idle - prev_idle
        prev_total, prev_idle = cur_total, cur_idle

        if delta_total <= 0:
            continue

        used_ratio = max(0.0, min(1.0, (delta_total - delta_idle) / delta_total))
        samples.append(used_ratio * 100.0)

    return samples


def _build_sources_from_repository() -> tuple[SimulatedSource, ...]:
    """Pick largest OPC UA server group and build test sources."""

    runtime_repo = SourceRuntimeConfigRepository()
    server_rows = runtime_repo.list_servers(
        group_by=("signal_profile_id", "application_protocol"),
        first_group_only=False,
    )
    grouped: dict[tuple[int, str], list] = defaultdict(list)
    for row in server_rows:
        grouped[(row.signal_profile_id, row.application_protocol)].append(row)

    opcua_groups = [
        (group_key, rows)
        for group_key, rows in grouped.items()
        if group_key[1].strip().lower().replace("_", "").replace("-", "") == "opcua"
    ]
    if not opcua_groups:
        raise AssertionError("Expected at least one OPC UA server group")

    selected_group_key, current_group_rows = max(opcua_groups, key=lambda item: len(item[1]))
    selected_profile_id, _ = selected_group_key

    point_rows = runtime_repo.list_profile_items(selected_profile_id)
    if len(point_rows) < VARIABLES_PER_SERVER:
        raise AssertionError(
            f"Profile items ({len(point_rows)}) < required variables/server ({VARIABLES_PER_SERVER})"
        )

    points = tuple(
        SimulatedPoint(
            ln_name=row.ln_name,
            do_name=row.do_name,
            unit=row.unit.strip() if row.unit is not None else None,
            data_type=row.data_type,
        )
        for row in point_rows[:VARIABLES_PER_SERVER]
    )

    return tuple(
        SimulatedSource(
            connection=SourceConnection(
                name=(row.asset_code or row.ld_name or row.ied_name or f"source_{row.endpoint_id}").strip(),
                ied_name=row.ied_name.strip(),
                ld_name=row.ld_name.strip(),
                host=row.host,
                port=int(row.port),
                transport=row.transport,
                protocol=row.application_protocol,
                namespace_uri=row.namespace_uri.strip(),
            ),
            points=points,
        )
        for row in current_group_rows
    )


async def _variable_count(source: SimulatedSource) -> int:
    """Read one source variable count from live reader."""

    async with build_source_reader(source.connection) as reader:
        node_infos = await reader.list_nodes()
    return len(node_infos)


def _node_paths_for_server(server: SimulatedSource) -> tuple[str, ...]:
    return tuple(f"s={logical_path(server.connection, point)}" for point in server.points)


def _start_offset_for_worker(
    *,
    worker_index: int,
    worker_count: int,
    target_interval_s: float,
) -> float:
    if STAGGER_MODE == "none" or worker_count <= 1:
        return 0.0
    return worker_index * target_interval_s / worker_count


def _normalize_timestamp(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return ensure_utc(value)


def _batch_server_timestamp(batch: tuple[SourceReadPoint, ...]) -> datetime | None:
    timestamps = [
        _normalize_timestamp(point.server_timestamp)
        for point in batch
        if point.server_timestamp is not None
    ]
    if not timestamps:
        return None
    return max(timestamps)


def _percentile(values: tuple[float, ...], q: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    position = (len(ordered) - 1) * q
    low_index = int(position)
    high_index = min(low_index + 1, len(ordered) - 1)
    weight = position - low_index
    return ordered[low_index] * (1.0 - weight) + ordered[high_index] * weight


def _evaluate_period(
    timestamps: tuple[datetime, ...],
    *,
    target_hz: float,
) -> tuple[int, int, float]:
    """Evaluate server_timestamp period against target sampling period."""

    if len(timestamps) < 2:
        return 0, 0, 0.0

    expected_period_s = 1.0 / target_hz
    tolerance_s = expected_period_s * PERIOD_TOLERANCE_RATIO

    deltas_s = tuple(
        max(0.0, (timestamps[index] - timestamps[index - 1]).total_seconds())
        for index in range(1, len(timestamps))
    )
    pass_count = sum(
        1
        for delta in deltas_s
        if abs(delta - expected_period_s) <= tolerance_s
    )
    errors_ms = tuple(abs(delta - expected_period_s) * 1000.0 for delta in deltas_s)
    return len(deltas_s), pass_count, _percentile(errors_ms, 0.95)


async def _poll_source_for_duration(
    source: SimulatedSource,
    *,
    node_paths: tuple[str, ...],
    target_hz: float,
    duration_s: float,
    measure_after_s: float,
    start_offset_s: float,
) -> WorkerMetrics:
    """Poll one server with full-batch reads for a fixed duration."""

    target_interval_s = 1.0 / target_hz
    started_at = time.monotonic() + start_offset_s
    deadline = started_at + duration_s
    measure_started_at = started_at + measure_after_s
    next_run_at = started_at

    completed_polls = 0
    batch_mismatches = 0
    read_errors = 0
    sampled_timestamps: list[datetime] = []

    async with build_source_reader(source.connection) as reader:
        while True:
            now = time.monotonic()
            if now >= deadline:
                break

            wait_seconds = max(0.0, next_run_at - now)
            if wait_seconds > 0:
                await asyncio.sleep(wait_seconds)

            cycle_started_at = time.monotonic()
            should_measure = cycle_started_at >= measure_started_at
            try:
                batch = await reader.read(node_paths, fast_mode=False)
            except Exception:
                if should_measure:
                    read_errors += 1
            else:
                if should_measure:
                    completed_polls += 1
                    if len(batch) != len(node_paths):
                        batch_mismatches += 1
                    ts = _batch_server_timestamp(batch)
                    if ts is not None:
                        sampled_timestamps.append(ts)

            next_run_at += target_interval_s

    measured_duration_s = duration_s - measure_after_s
    achieved_hz = completed_polls / measured_duration_s if measured_duration_s > 0 else 0.0
    period_sample_count, period_pass_count, period_p95_error_ms = _evaluate_period(
        tuple(sampled_timestamps),
        target_hz=target_hz,
    )

    return WorkerMetrics(
        completed_polls=completed_polls,
        batch_mismatches=batch_mismatches,
        read_errors=read_errors,
        achieved_hz=achieved_hz,
        period_sample_count=period_sample_count,
        period_pass_count=period_pass_count,
        period_p95_error_ms=period_p95_error_ms,
    )


async def _run_level(
    servers: tuple[SimulatedSource, ...],
    *,
    expected_variable_count: int,
    target_hz: float,
) -> LevelResult:
    """Run one (server_count, target_hz) level."""

    target_interval_s = 1.0 / target_hz
    stop_event = asyncio.Event()
    cpu_task = asyncio.create_task(_sample_cpu_percent(stop_event))

    try:
        worker_results = tuple(
            await asyncio.gather(
                *(
                    _poll_source_for_duration(
                        server,
                        node_paths=_node_paths_for_server(server),
                        target_hz=target_hz,
                        duration_s=LOAD_LEVEL_DURATION_S,
                        measure_after_s=MEASURE_AFTER_S,
                        start_offset_s=_start_offset_for_worker(
                            worker_index=index,
                            worker_count=len(servers),
                            target_interval_s=target_interval_s,
                        ),
                    )
                    for index, server in enumerate(servers)
                )
            )
        )
    finally:
        stop_event.set()

    cpu_samples = await cpu_task

    achieved_hz_values = tuple(item.achieved_hz for item in worker_results)
    completed_polls_total = sum(item.completed_polls for item in worker_results)
    batch_mismatches_total = sum(item.batch_mismatches for item in worker_results)
    read_errors_total = sum(item.read_errors for item in worker_results)
    period_samples_total = sum(item.period_sample_count for item in worker_results)
    period_pass_total = sum(item.period_pass_count for item in worker_results)
    period_p95_error_ms = max(
        (item.period_p95_error_ms for item in worker_results),
        default=0.0,
    )

    period_pass_ratio = (
        period_pass_total / period_samples_total if period_samples_total > 0 else 0.0
    )
    cpu_mean_percent = statistics.mean(cpu_samples) if cpu_samples else 0.0
    cpu_peak_percent = max(cpu_samples, default=0.0)

    passed = (
        batch_mismatches_total == 0
        and read_errors_total == 0
        and period_samples_total >= len(servers) * MIN_PERIOD_SAMPLES
        and period_pass_ratio >= PERIOD_PASS_RATIO
        and cpu_peak_percent <= CPU_LIMIT_PERCENT
    )

    return LevelResult(
        server_count=len(servers),
        target_hz=target_hz,
        expected_variable_count=expected_variable_count,
        completed_polls_total=completed_polls_total,
        batch_mismatches_total=batch_mismatches_total,
        read_errors_total=read_errors_total,
        achieved_hz_min=min(achieved_hz_values, default=0.0),
        achieved_hz_mean=statistics.mean(achieved_hz_values) if achieved_hz_values else 0.0,
        period_samples_total=period_samples_total,
        period_pass_ratio=period_pass_ratio,
        period_p95_error_ms=period_p95_error_ms,
        cpu_mean_percent=cpu_mean_percent,
        cpu_peak_percent=cpu_peak_percent,
        passed=passed,
    )


async def _run_server_level(
    context: LoadTestContext,
    *,
    server_count: int,
) -> ServerRampSummary:
    """Run sampling-rate ramp for one server-count level."""

    servers = context.servers[:server_count]
    levels: list[LevelResult] = []

    for target_hz in SAMPLE_HZ_RAMP:
        levels.append(
            await _run_level(
                servers,
                expected_variable_count=context.expected_variable_count,
                target_hz=target_hz,
            )
        )

    max_pass_hz: float | None = None
    for level in levels:
        if not level.passed:
            break
        max_pass_hz = level.target_hz

    return ServerRampSummary(
        server_count=server_count,
        max_pass_hz=max_pass_hz,
        levels=tuple(levels),
    )


def _report_table(levels: tuple[LevelResult, ...]) -> str:
    lines = [
        "| target_hz | servers | vars/server | completed_polls | achieved_hz_min | achieved_hz_mean | period_samples | period_pass_ratio | period_p95_error_ms | cpu_mean% | cpu_peak% | mismatches | read_errors | passed |",
        "|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|:---:|",
    ]
    for item in levels:
        lines.append(
            "| "
            f"{item.target_hz:.1f} | "
            f"{item.server_count} | "
            f"{item.expected_variable_count} | "
            f"{item.completed_polls_total} | "
            f"{item.achieved_hz_min:.2f} | "
            f"{item.achieved_hz_mean:.2f} | "
            f"{item.period_samples_total} | "
            f"{item.period_pass_ratio:.3f} | "
            f"{item.period_p95_error_ms:.1f} | "
            f"{item.cpu_mean_percent:.1f} | "
            f"{item.cpu_peak_percent:.1f} | "
            f"{item.batch_mismatches_total} | "
            f"{item.read_errors_total} | "
            f"{'yes' if item.passed else 'no'} |"
        )
    return "\n".join(lines)


def _write_report(results: tuple[ServerRampSummary, ...]) -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    lines: list[str] = [
        "# Source Simulator Load Report",
        "",
        "## Config",
        "",
        f"- Variables per server: {VARIABLES_PER_SERVER}",
        f"- Source update rate: {SOURCE_UPDATE_HZ:.1f}Hz",
        f"- Level duration: {LOAD_LEVEL_DURATION_S:.1f}s",
        f"- Warmup: {WARMUP_S:.1f}s",
        f"- Measure after: {MEASURE_AFTER_S:.1f}s",
        f"- CPU limit: {CPU_LIMIT_PERCENT:.1f}%",
        f"- Period tolerance: target_interval * {PERIOD_TOLERANCE_RATIO:.2f}",
        f"- Period pass ratio threshold: {PERIOD_PASS_RATIO:.2f}",
        f"- Server ramp: {', '.join(str(v) for v in SERVER_RAMP)}",
        f"- Sample Hz ramp: {', '.join(str(v) for v in SAMPLE_HZ_RAMP)}",
        "",
        "## Max sustainable sampling rate by server count",
        "",
        "| servers | max_pass_hz |",
        "|---:|---:|",
    ]

    for summary in results:
        max_hz = f"{summary.max_pass_hz:.1f}" if summary.max_pass_hz is not None else "none"
        lines.append(f"| {summary.server_count} | {max_hz} |")

    for summary in results:
        lines.extend(
            [
                "",
                f"## Server count = {summary.server_count}",
                "",
                _report_table(summary.levels),
            ]
        )

    REPORT_PATH.write_text("\n".join(lines), encoding="utf-8")


@contextmanager
def _load_test_context(required_server_count: int) -> LoadTestContext:
    """Start simulator fleet and verify fixed variable count requirement."""

    sources = _build_sources_from_repository()
    if len(sources) < required_server_count:
        raise AssertionError(
            f"Expected at least {required_server_count} servers, got {len(sources)}"
        )

    selected_servers = sources[:required_server_count]

    for server in selected_servers:
        if len(server.points) != VARIABLES_PER_SERVER:
            raise AssertionError(
                f"Server {server.connection.name} points={len(server.points)} "
                f"!= fixed {VARIABLES_PER_SERVER}"
            )

    fleet = SourceSimulatorFleet.create(
        sources=selected_servers,
        update_config=UpdateConfig(
            enabled=True,
            interval_seconds=SOURCE_UPDATE_INTERVAL_S,
            update_count=VARIABLES_PER_SERVER,
        ),
    )

    with fleet:
        time.sleep(WARMUP_S)
        live_count = asyncio.run(_variable_count(selected_servers[0]))
        assert live_count >= VARIABLES_PER_SERVER, (
            f"Expected at least {VARIABLES_PER_SERVER} live variables, got {live_count}"
        )

        yield LoadTestContext(
            servers=selected_servers,
            expected_variable_count=VARIABLES_PER_SERVER,
        )


@pytest.mark.load
def test_source_simulation_sampling_capacity_under_cpu_budget() -> None:
    """Find max sustainable sampling rate for different server counts."""

    required_server_count = max(SERVER_RAMP)
    with _load_test_context(required_server_count=required_server_count) as context:
        results = tuple(
            asyncio.run(_run_server_level(context, server_count=server_count))
            for server_count in SERVER_RAMP
        )

    _write_report(results)

    for summary in results:
        first_level = summary.levels[0]
        assert first_level.passed, (
            f"Baseline failed for server_count={summary.server_count}, "
            f"target_hz={first_level.target_hz:.1f}; see {REPORT_PATH}"
        )
        assert summary.max_pass_hz is not None, (
            f"No sustainable sampling level found for server_count={summary.server_count}; "
            f"see {REPORT_PATH}"
        )
