"""Load tests for source_simulation OPC UA polling capacity.

Run examples:
    SOURCE_SIM_LOAD_LEVEL_DURATION_S=3 pytest -q tests/performance/load/test_source_simulation_load.py -s
    SOURCE_SIM_LOAD_POLL_HZ_RAMP=10,20,30,40 pytest -q tests/performance/load/test_source_simulation_load.py -s
    SOURCE_SIM_LOAD_SERVER_RAMP=1,5,10,15,20,25,30 pytest -q tests/performance/load/test_source_simulation_load.py -s
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
from tools.source_simulation.adapters.opcua.nodeset_builder import logical_path
from tools.source_simulation.adapters.registry import build_source_reader
from tools.source_simulation.domain import (
    SimulatedPoint,
    SimulatedSource,
    SourceConnection,
    UpdateConfig,
)
from tools.source_simulation.fleet import SourceSimulatorFleet

# 每个压力层级持续时长。
# 建议本地先用 2~3 秒快速摸底，再按需要拉长。
LOAD_LEVEL_DURATION_S = float(os.environ.get("SOURCE_SIM_LOAD_LEVEL_DURATION_S", "3"))
# fleet 启动后的预热时间，避免把 server 刚启动时的波动算进结果。
WARMUP_S = float(os.environ.get("SOURCE_SIM_LOAD_WARMUP_S", "1"))
# 每个层级内部再额外丢弃前面的预热窗口，只统计后半段稳定数据。
MEASURE_AFTER_S = float(os.environ.get("SOURCE_SIM_LOAD_MEASURE_AFTER_S", "0"))
# 场景 1：单 server，全量读取，逐步提高 polling 频率。
POLL_HZ_RAMP = tuple(
    int(part.strip())
    for part in os.environ.get("SOURCE_SIM_LOAD_POLL_HZ_RAMP", "10,20,30,40,50").split(",")
    if part.strip()
)
# 场景 2：固定 10Hz，全量读取，逐步增加 server 数。
SERVER_RAMP = tuple(
    int(part.strip())
    for part in os.environ.get("SOURCE_SIM_LOAD_SERVER_RAMP", ",".join(str(i) for i in range(1, 21, 5))).split(",")
    if part.strip()
)
# 认为“达标”的最低实际频率比例。
# 例如目标 10Hz，阈值 0.95，则最低要求达到 9.5Hz。
SUCCESS_RATE_RATIO = float(os.environ.get("SOURCE_SIM_LOAD_SUCCESS_RATE_RATIO", "0.95"))
STAGGER_MODE = os.environ.get("SOURCE_SIM_LOAD_STAGGER_MODE", "none").strip().lower()
OUTPUT_DIR = Path(os.environ.get("SOURCE_SIM_LOAD_OUTPUT_DIR", "tests/tmp"))
SINGLE_SERVER_REPORT_PATH = OUTPUT_DIR / "source_simulation_load_single_server_report.md"
MULTI_SERVER_REPORT_PATH = OUTPUT_DIR / "source_simulation_load_multi_server_report.md"
# simulator 本身的更新频率固定为 10Hz。
SOURCE_UPDATE_HZ = 10.0
SOURCE_UPDATE_INTERVAL_S = 1.0 / SOURCE_UPDATE_HZ

if STAGGER_MODE not in {"none", "even"}:
    raise ValueError(f"Unsupported SOURCE_SIM_LOAD_STAGGER_MODE: {STAGGER_MODE!r}")


@dataclass(frozen=True, slots=True)
class PollLevelResult:
    """一个负载层级的汇总结果。"""

    mode: str
    level: int
    server_count: int
    target_hz: float
    expected_variable_count: int
    target_points_per_second: float
    completed_points_per_second: float
    completed_polls: int
    batch_mismatches: int
    read_errors: int
    late_loops: int
    late_loop_ratio: float
    measured_duration_s: float
    achieved_hz_min: float
    achieved_hz_mean: float
    cycle_p95_ms: float
    passed: bool


@dataclass(frozen=True, slots=True)
class WorkerResult:
    """单个 server 在一个层级里的 polling 结果。"""

    completed_polls: int
    batch_mismatches: int
    read_errors: int
    late_loops: int
    achieved_hz: float
    cycle_durations_ms: tuple[float, ...]


@dataclass(frozen=True, slots=True)
class LoadTestContext:
    """负载测试共享上下文。"""

    servers: tuple[SimulatedSource, ...]
    expected_variable_count: int


def _build_sources_from_repository() -> tuple[SimulatedSource, ...]:
    """从仓库配置中挑出一个最大的 OPC UA 组作为压测样本。"""

    runtime_repo = SourceRuntimeConfigRepository()
    server_rows = runtime_repo.list_servers(
        group_by=("signal_profile_id", "application_protocol"),
        first_group_only=False,
    )
    grouped_server_rows: dict[tuple[int, str], list] = defaultdict(list)
    for row in server_rows:
        grouped_server_rows[(row.signal_profile_id, row.application_protocol)].append(row)

    opcua_groups = [
        (group_key, rows)
        for group_key, rows in grouped_server_rows.items()
        if group_key[1].strip().lower().replace("_", "").replace("-", "") == "opcua"
    ]
    if not opcua_groups:
        raise AssertionError("Expected at least one OPC UA server group from repository")

    selected_group_key, current_group_rows = max(opcua_groups, key=lambda item: len(item[1]))
    selected_profile_id, _ = selected_group_key
    point_rows = runtime_repo.list_profile_items(selected_profile_id)
    points = tuple(
        SimulatedPoint(
            ln_name=row.ln_name,
            do_name=row.do_name,
            unit=row.unit.strip() if row.unit is not None else None,
            data_type=row.data_type,
        )
        for row in point_rows
    )
    if not points:
        raise AssertionError(f"Expected profile items for signal_profile_id={selected_profile_id}")

    sources = tuple(
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
    if not sources:
        raise AssertionError("Expected at least one OPC UA source for load test")
    return sources


async def _variable_count(source: SimulatedSource) -> int:
    """读取一个 source 的变量总数，用来校验 profile 与地址空间是否一致。"""

    async with build_source_reader(source.connection) as reader:
        node_infos = await reader.list_nodes()
    return len(node_infos)


def _node_paths_for_server(server: SimulatedSource) -> tuple[str, ...]:
    """按一组共享 points 和当前 server 的连接信息生成读取路径。"""

    return tuple(
        f"s={logical_path(server.connection, point)}"
        for point in server.points
    )


def _start_offset_for_worker(
    *,
    worker_index: int,
    worker_count: int,
    target_interval_s: float,
) -> float:
    if STAGGER_MODE == "none":
        return 0.0
    if STAGGER_MODE == "even":
        if worker_count <= 0:
            raise ValueError("worker_count must be greater than 0")
        if worker_index < 0 or worker_index >= worker_count:
            raise ValueError("worker_index must be in [0, worker_count)")
        if target_interval_s < 0:
            raise ValueError("target_interval_s must be greater than or equal to 0")
        if worker_count == 1 or target_interval_s == 0:
            return 0.0
        return worker_index * target_interval_s / worker_count
    raise ValueError(f"Unsupported SOURCE_SIM_LOAD_STAGGER_MODE: {STAGGER_MODE!r}")


async def _poll_source_for_duration(
    source: SimulatedSource,
    *,
    node_paths: tuple[str, ...],
    target_hz: float,
    duration_s: float,
    measure_after_s: float,
    start_offset_s: float = 0.0,
) -> WorkerResult:
    """在固定时长内，以目标频率对单个 server 做全量批量 polling。"""

    if measure_after_s < 0:
        raise ValueError("measure_after_s must be greater than or equal to 0")
    if measure_after_s >= duration_s:
        raise ValueError("measure_after_s must be less than duration_s")
    if start_offset_s < 0:
        raise ValueError("start_offset_s must be greater than or equal to 0")

    target_interval_s = 1.0 / target_hz
    base_started_at = time.monotonic()
    started_at = base_started_at + start_offset_s
    deadline = started_at + duration_s
    measure_started_at = started_at + measure_after_s
    next_run_at = started_at
    completed_polls = 0
    batch_mismatches = 0
    read_errors = 0
    late_loops = 0
    cycle_durations_ms: list[float] = []

    async with build_source_reader(source.connection) as reader:
        while True:
            now = time.monotonic()
            if now >= deadline:
                break

            # 如果当前时间已经明显超过下一轮计划时间，说明调度开始积压。
            if now > next_run_at + target_interval_s:
                late_loops += 1

            wait_seconds = max(0.0, next_run_at - now)
            if wait_seconds > 0:
                await asyncio.sleep(wait_seconds)

            cycle_started_at = time.monotonic()
            should_measure = cycle_started_at >= measure_started_at
            try:
                # 这里每一轮都是“全量变量读取”，是本测试真正施加的负载。
                batch = await reader.read(node_paths, fast_mode=False)
            except Exception:
                if should_measure:
                    read_errors += 1
            else:
                if should_measure:
                    completed_polls += 1
                # 理论上 batch 大小应始终等于变量总数，否则视为结果不完整。
                if should_measure and len(batch) != len(node_paths):
                    batch_mismatches += 1

            if should_measure:
                cycle_durations_ms.append((time.monotonic() - cycle_started_at) * 1000.0)
            next_run_at += target_interval_s

    measured_duration_s = duration_s - measure_after_s
    achieved_hz = completed_polls / measured_duration_s if measured_duration_s > 0 else 0.0
    return WorkerResult(
        completed_polls=completed_polls,
        batch_mismatches=batch_mismatches,
        read_errors=read_errors,
        late_loops=late_loops,
        achieved_hz=achieved_hz,
        cycle_durations_ms=tuple(cycle_durations_ms),
    )


def _percentile(values: tuple[float, ...], q: float) -> float:
    """计算简单分位数，用于输出每个 worker 的 cycle p95。"""

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


async def _run_poll_level(
    servers: tuple[SimulatedSource, ...],
    *,
    expected_variable_count: int,
    mode: str,
    level: int,
    target_hz: float,
    duration_s: float,
    measure_after_s: float = MEASURE_AFTER_S,
) -> PollLevelResult:
    """运行一个负载层级，并把多个 server 的结果汇总成一条记录。"""

    target_interval_s = 1.0 / target_hz
    worker_count = len(servers)
    worker_results = tuple(
        await asyncio.gather(
            *(
                _poll_source_for_duration(
                    server,
                    node_paths=_node_paths_for_server(server),
                    target_hz=target_hz,
                    duration_s=duration_s,
                    measure_after_s=measure_after_s,
                    start_offset_s=_start_offset_for_worker(
                        worker_index=index,
                        worker_count=worker_count,
                        target_interval_s=target_interval_s,
                    ),
                )
                for index, server in enumerate(servers)
            )
        )
    )

    achieved_hz_values = tuple(result.achieved_hz for result in worker_results)
    cycle_p95_values = tuple(
        _percentile(result.cycle_durations_ms, 0.95)
        for result in worker_results
        if result.cycle_durations_ms
    )
    batch_mismatches = sum(result.batch_mismatches for result in worker_results)
    read_errors = sum(result.read_errors for result in worker_results)
    late_loops = sum(result.late_loops for result in worker_results)
    completed_polls = sum(result.completed_polls for result in worker_results)
    measured_duration_s = duration_s - measure_after_s
    target_points_per_second = len(servers) * target_hz * expected_variable_count
    completed_points_per_second = (
        completed_polls * expected_variable_count / measured_duration_s
        if measured_duration_s > 0
        else 0.0
    )
    expected_polls_per_worker = int(measured_duration_s * target_hz)
    expected_polls_total = expected_polls_per_worker * len(servers)
    late_loop_ratio = late_loops / max(expected_polls_total, 1)
    achieved_hz_min = min(achieved_hz_values, default=0.0)
    achieved_hz_mean = statistics.mean(achieved_hz_values) if achieved_hz_values else 0.0
    cycle_p95_ms = max(cycle_p95_values, default=0.0)
    # 通过标准：
    # 1. 没有变量数不完整；
    # 2. 没有读异常；
    # 3. 最慢的 worker 也达到目标频率阈值。
    passed = (
        batch_mismatches == 0
        and read_errors == 0
        and achieved_hz_min >= target_hz * SUCCESS_RATE_RATIO
    )

    return PollLevelResult(
        mode=mode,
        level=level,
        server_count=len(servers),
        target_hz=target_hz,
        expected_variable_count=expected_variable_count,
        target_points_per_second=target_points_per_second,
        completed_points_per_second=completed_points_per_second,
        completed_polls=completed_polls,
        batch_mismatches=batch_mismatches,
        read_errors=read_errors,
        late_loops=late_loops,
        late_loop_ratio=late_loop_ratio,
        measured_duration_s=measured_duration_s,
        achieved_hz_min=achieved_hz_min,
        achieved_hz_mean=achieved_hz_mean,
        cycle_p95_ms=cycle_p95_ms,
        passed=passed,
    )


async def _run_frequency_ramp(
    context: LoadTestContext,
) -> tuple[PollLevelResult, ...]:
    """异步执行单 server 提频率场景。"""

    results: list[PollLevelResult] = []
    for level in POLL_HZ_RAMP:
        results.append(
            await _run_poll_level(
                context.servers[:1],
                expected_variable_count=context.expected_variable_count,
                mode="single_server_poll_hz_ramp",
                level=level,
                target_hz=float(level),
                duration_s=LOAD_LEVEL_DURATION_S,
            )
        )
    return tuple(results)


async def _run_server_ramp(
    context: LoadTestContext,
) -> tuple[PollLevelResult, ...]:
    """异步执行多 server 固定 10Hz 场景。

    每个层级内部会并发 polling 多个 server；
    层级之间保持顺序推进，用于得到清晰的容量拐点。
    """

    results: list[PollLevelResult] = []
    for level in SERVER_RAMP:
        results.append(
            await _run_poll_level(
                context.servers[:level],
                expected_variable_count=context.expected_variable_count,
                mode="multi_server_ramp",
                level=level,
                target_hz=SOURCE_UPDATE_HZ,
                duration_s=LOAD_LEVEL_DURATION_S,
            )
        )
    return tuple(results)


def _max_consecutive_passed(level_results: tuple[PollLevelResult, ...]) -> PollLevelResult | None:
    """取 ramp 中“连续通过”的最后一个层级，作为当前可承受上限。"""

    last_passed: PollLevelResult | None = None
    for result in level_results:
        if not result.passed:
            break
        last_passed = result
    return last_passed


def _report_table(level_results: tuple[PollLevelResult, ...]) -> str:
    """把层级结果渲染成 markdown 表格。"""

    lines = [
        "| level | servers | target_hz | vars/server | target_points/s | completed_points/s | achieved_hz_min | achieved_hz_mean | p95_cycle_ms | mismatches | read_errors | late_loops | late_loop_ratio | passed |",
        "|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|:---:|",
    ]
    for result in level_results:
        lines.append(
            "| "
            f"{result.level} | "
            f"{result.server_count} | "
            f"{result.target_hz:.1f} | "
            f"{result.expected_variable_count} | "
            f"{result.target_points_per_second:.1f} | "
            f"{result.completed_points_per_second:.1f} | "
            f"{result.achieved_hz_min:.2f} | "
            f"{result.achieved_hz_mean:.2f} | "
            f"{result.cycle_p95_ms:.1f} | "
            f"{result.batch_mismatches} | "
            f"{result.read_errors} | "
            f"{result.late_loops} | "
            f"{result.late_loop_ratio:.3f} | "
            f"{'yes' if result.passed else 'no'} |"
        )
    return "\n".join(lines)


def _write_single_server_report(
    *,
    variable_results: tuple[PollLevelResult, ...],
) -> None:
    """写出单 server 提频率场景的 markdown 报告。"""

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    max_poll_level = _max_consecutive_passed(variable_results)

    report = "\n".join(
        [
            "# Source Simulation Load Report",
            "",
            "## Config",
            "",
            f"- Source update rate: {SOURCE_UPDATE_HZ:.1f}Hz",
            f"- Load level duration: {LOAD_LEVEL_DURATION_S:.1f}s",
            f"- Warmup: {WARMUP_S:.1f}s",
            f"- Measure after: {MEASURE_AFTER_S:.1f}s",
            f"- Measured duration: {LOAD_LEVEL_DURATION_S - MEASURE_AFTER_S:.1f}s",
            f"- Stagger mode: {STAGGER_MODE}",
            f"- Poll Hz ramp: {', '.join(str(level) for level in POLL_HZ_RAMP)}",
            f"- Success rate threshold: {SUCCESS_RATE_RATIO:.2f}",
            "",
            "## Scenario: One server, full polling, increase polling frequency",
            "",
            (
                f"- Max sustained polling frequency: {max_poll_level.target_hz:.1f}Hz "
                f"({max_poll_level.expected_variable_count} variables/server)"
                if max_poll_level is not None
                else "- Max sustained polling frequency: none"
            ),
            "",
            _report_table(variable_results),
            "",
        ]
    )
    SINGLE_SERVER_REPORT_PATH.write_text(report, encoding="utf-8")


def _write_multi_server_report(
    *,
    server_results: tuple[PollLevelResult, ...],
) -> None:
    """写出多 server 固定 10Hz 场景的 markdown 报告。"""

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    max_server_level = _max_consecutive_passed(server_results)

    report = "\n".join(
        [
            "# Source Simulation Load Report",
            "",
            "## Config",
            "",
            f"- Source update rate: {SOURCE_UPDATE_HZ:.1f}Hz",
            f"- Load level duration: {LOAD_LEVEL_DURATION_S:.1f}s",
            f"- Warmup: {WARMUP_S:.1f}s",
            f"- Measure after: {MEASURE_AFTER_S:.1f}s",
            f"- Measured duration: {LOAD_LEVEL_DURATION_S - MEASURE_AFTER_S:.1f}s",
            f"- Stagger mode: {STAGGER_MODE}",
            f"- Server ramp: {', '.join(str(level) for level in SERVER_RAMP)}",
            f"- Success rate threshold: {SUCCESS_RATE_RATIO:.2f}",
            "",
            "## Scenario: Keep 10Hz, increase server count",
            "",
            (
                f"- Max sustained server count: {max_server_level.server_count} "
                f"at {max_server_level.target_hz:.1f}Hz"
                if max_server_level is not None
                else "- Max sustained server count: none"
            ),
            "",
            _report_table(server_results),
            "",
        ]
    )
    MULTI_SERVER_REPORT_PATH.write_text(report, encoding="utf-8")


@contextmanager
def _load_test_context(
    required_server_count: int,
    *,
    update_enabled: bool,
) -> LoadTestContext:
    """启动 fleet 并准备全量节点列表，供两个测试场景复用。"""

    servers = _build_sources_from_repository()
    if len(servers) < required_server_count:
        raise AssertionError(
            f"Expected at least {required_server_count} servers, got {len(servers)}"
        )

    selected_servers = servers[:required_server_count]
    fleet = SourceSimulatorFleet.create(
        sources=selected_servers,
        update_config=UpdateConfig(
            enabled=update_enabled,
            interval_seconds=SOURCE_UPDATE_INTERVAL_S,
            update_count=len(selected_servers[0].points),
        ),
    )

    with fleet:
        time.sleep(WARMUP_S)
        expected_variable_count = asyncio.run(_variable_count(selected_servers[0]))
        assert expected_variable_count == len(selected_servers[0].points), (
            f"Expected {len(selected_servers[0].points)} variables from repository profile, "
            f"got {expected_variable_count}"
        )
        yield LoadTestContext(
            servers=selected_servers,
            expected_variable_count=expected_variable_count,
        )


@pytest.mark.load
def test_source_simulation_single_server_polling_load_capacity() -> None:
    """单 server 全量读取，逐步提高 polling 频率。"""

    if not POLL_HZ_RAMP:
        raise AssertionError("SOURCE_SIM_LOAD_POLL_HZ_RAMP must not be empty")

    with _load_test_context(required_server_count=1, update_enabled=False) as context:
        variable_results = asyncio.run(_run_frequency_ramp(context))

    _write_single_server_report(variable_results=variable_results)
    max_poll_level = _max_consecutive_passed(variable_results)

    assert variable_results[0].passed, (
        f"Baseline single-server polling level {variable_results[0].target_hz:.1f}Hz failed; "
        f"see {SINGLE_SERVER_REPORT_PATH}"
    )
    assert max_poll_level is not None, (
        f"No sustainable single-server polling level found; see {SINGLE_SERVER_REPORT_PATH}"
    )


@pytest.mark.load
def test_source_simulation_multi_server_polling_load_capacity() -> None:
    """固定 10Hz 全量读取，逐步增加 server 数量。"""

    if not SERVER_RAMP:
        raise AssertionError("SOURCE_SIM_LOAD_SERVER_RAMP must not be empty")

    required_server_count = max(1, max(SERVER_RAMP))
    with _load_test_context(
        required_server_count=required_server_count,
        update_enabled=False,
    ) as context:
        multi_server_results = asyncio.run(_run_server_ramp(context))

    _write_multi_server_report(server_results=multi_server_results)
    max_server_level = _max_consecutive_passed(multi_server_results)

    assert multi_server_results[0].passed, (
        f"Baseline multi-server level {multi_server_results[0].server_count} failed; "
        f"see {MULTI_SERVER_REPORT_PATH}"
    )
    assert max_server_level is not None, (
        f"No sustainable multi-server level found; see {MULTI_SERVER_REPORT_PATH}"
    )
