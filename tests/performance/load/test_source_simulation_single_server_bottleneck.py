"""单 server OPC UA 仿真读取最大可用频率诊断测试。

本文件用于定位 source_simulation 单台 OPC UA 仿真服务器的最大可持续全量读取频率。

测试目标：
1. 只启动 1 个 simulator server；
2. 每个 tick 批量读取该 server 的全部变量；
3. 从 HZ_START 开始，按 HZ_STEP 自动升频；
4. 每个频率档位统计：
   - read_attributes 耗时；
   - 后处理耗时；
   - 完整 tick 耗时；
   - 客户端采样周期稳定性；
   - missed tick；
   - ServerTimestamp 观察值；
   - CPU 使用率；
5. 直到首次失败，输出最大通过频率；
6. ServerTimestamp 只用于观察服务端刷新，不参与客户端采样通过判定；
7. max 只作为异常尖峰观察，不直接作为失败条件。

运行示例：
    SOURCE_SIM_LOAD_HZ_START=1 \
    SOURCE_SIM_LOAD_HZ_STEP=2 \
    SOURCE_SIM_LOAD_HZ_MAX=200 \
    SOURCE_SIM_LOAD_LEVEL_DURATION_S=20 \
    SOURCE_SIM_LOAD_WARMUP_S=5 \
    SOURCE_SIM_LOAD_SOURCE_UPDATE_ENABLED=true \
    python -m pytest tests/performance/load/test_source_simulation_single_server_bottleneck.py -s -v

关闭服务端周期写入对照：
    SOURCE_SIM_LOAD_SOURCE_UPDATE_ENABLED=false \
    python -m pytest tests/performance/load/test_source_simulation_single_server_bottleneck.py -s -v
"""

from __future__ import annotations

import asyncio
import os
import random
import socket
import statistics
import sys
import time
from collections import defaultdict
from collections.abc import Sequence
from contextlib import contextmanager
from dataclasses import dataclass, replace
from datetime import datetime
from pathlib import Path
from typing import Iterator

_PROJECT_ROOT = Path(__file__).resolve().parents[3]
_SRC_ROOT = _PROJECT_ROOT / "src"
for _path in (str(_PROJECT_ROOT), str(_SRC_ROOT)):
    if _path not in sys.path:
        sys.path.insert(0, _path)

import asyncua.ua as ua  # type: ignore[import-untyped]
import pytest
from asyncua import Client  # type: ignore[import-untyped]

from tools.source_simulation.adapters.opcua.nodeset_builder import logical_path
from tools.source_simulation.domain import (
    SimulatedPoint,
    SimulatedSource,
    SourceConnection,
    UpdateConfig,
)
from tools.source_simulation.fleet import SourceSimulatorFleet
from whale.ingest.adapters.config.source_runtime_config_repository import (
    SourceRuntimeConfigRepository,
)

LOAD_LEVEL_DURATION_S = float(os.environ.get("SOURCE_SIM_LOAD_LEVEL_DURATION_S", "20"))
WARMUP_S = float(os.environ.get("SOURCE_SIM_LOAD_WARMUP_S", "5"))

HZ_START = float(os.environ.get("SOURCE_SIM_LOAD_HZ_START", "1"))
HZ_STEP = float(os.environ.get("SOURCE_SIM_LOAD_HZ_STEP", "2"))
HZ_MAX = float(os.environ.get("SOURCE_SIM_LOAD_HZ_MAX", "200"))

READ_TIMEOUT_S = float(os.environ.get("SOURCE_SIM_LOAD_READ_TIMEOUT_S", "5"))

SOURCE_UPDATE_HZ = float(os.environ.get("SOURCE_SIM_LOAD_SOURCE_UPDATE_HZ", "10"))
SOURCE_UPDATE_ENABLED = (
    os.environ.get("SOURCE_SIM_LOAD_SOURCE_UPDATE_ENABLED", "true")
    .strip()
    .lower()
    not in {"0", "false", "no", "off"}
)

PERIOD_TOLERANCE_RATIO = float(os.environ.get("SOURCE_SIM_LOAD_PERIOD_TOLERANCE_RATIO", "0.2"))
PERIOD_PASS_RATIO = float(os.environ.get("SOURCE_SIM_LOAD_PERIOD_PASS_RATIO", "0.95"))
ACHIEVED_PASS_RATIO = float(os.environ.get("SOURCE_SIM_LOAD_ACHIEVED_PASS_RATIO", "0.95"))

# missed tick 不建议 1 次即失败，否则容易把 OS 调度抖动误判为能力上限。
MISSED_PASS_RATIO = float(os.environ.get("SOURCE_SIM_LOAD_MISSED_PASS_RATIO", "0.02"))

MIN_EXPECTED_POINT_COUNT = int(os.environ.get("SOURCE_SIM_LOAD_MIN_POINTS", "300"))
MAX_EXPECTED_POINT_COUNT = int(os.environ.get("SOURCE_SIM_LOAD_MAX_POINTS", "500"))

# 尖峰阈值：超过 target_period * SPIKE_RATIO_OF_PERIOD 记为 spike。
SPIKE_RATIO_OF_PERIOD = float(os.environ.get("SOURCE_SIM_LOAD_SPIKE_RATIO_OF_PERIOD", "0.5"))


@dataclass(frozen=True, slots=True)
class ReadOnceResult:
    """单次 OPC UA 批量读取原始结果。"""

    ok: bool
    data_values: Sequence | None
    read_cost_ms: float


@dataclass(frozen=True, slots=True)
class ProcessResult:
    """单次读取后的后处理结果。"""

    ok: bool
    value_count: int
    server_timestamp: datetime | None
    batch_mismatch: bool


@dataclass(frozen=True, slots=True)
class TickResult:
    """单个 tick 的完整处理结果。"""

    ok: bool
    value_count: int
    server_timestamp: datetime | None
    read_ms: float
    post_ms: float
    tick_ms: float
    batch_mismatch: bool


@dataclass(frozen=True, slots=True)
class LevelResult:
    """单 server 某一目标频率档位的诊断结果。"""

    target_hz: float
    target_period_ms: float
    expected_variable_count: int

    expected_ticks: int
    completed_ticks: int
    failed_ticks: int
    missed_ticks: int
    missed_ratio: float
    achieved_hz: float
    achieved_ratio: float

    read_mean_ms: float
    read_p50_ms: float
    read_p95_ms: float
    read_p99_ms: float
    read_max_ms: float
    read_spike_count: int

    post_mean_ms: float
    post_p50_ms: float
    post_p95_ms: float
    post_p99_ms: float
    post_max_ms: float
    post_spike_count: int

    tick_mean_ms: float
    tick_p50_ms: float
    tick_p95_ms: float
    tick_p99_ms: float
    tick_max_ms: float
    tick_spike_count: int

    client_period_samples: int
    client_period_pass_ratio: float
    client_period_p95_error_ms: float
    client_period_p99_error_ms: float

    server_timestamp_unique_count: int
    server_timestamp_observed_hz: float
    server_timestamp_period_p95_error_ms: float

    batch_mismatches: int
    read_errors: int

    cpu_mean_percent: float
    cpu_peak_percent: float

    passed: bool
    failure_reason: str


@dataclass(frozen=True, slots=True)
class RampResult:
    """单 server 自动升频诊断汇总。"""

    max_pass_hz: float | None
    levels: tuple[LevelResult, ...]


@dataclass(frozen=True, slots=True)
class LoadTestContext:
    """单 server 诊断上下文。"""

    source: SimulatedSource
    expected_variable_count: int
    assigned_port: int


@dataclass(slots=True)
class OpcUaSingleServerReader:
    """单个 OPC UA server 的长连接批量读取器。"""

    source: SimulatedSource
    client: Client | None = None
    nodes: list | None = None

    async def connect(self) -> None:
        """建立 OPC UA 长连接，并缓存全部变量节点。"""
        self.client = Client(url=_build_opcua_endpoint(self.source.connection))
        await self.client.__aenter__()

        namespace_uri = str(self.source.connection.namespace_uri)
        ns_idx = await self.client.get_namespace_index(namespace_uri)

        self.nodes = [
            self.client.get_node(
                f"ns={ns_idx};s={logical_path(self.source.connection, point)}"
            )
            for point in self.source.points
        ]

    async def close(self) -> None:
        """关闭 OPC UA 长连接。"""
        if self.client is None:
            return

        try:
            await self.client.__aexit__(None, None, None)
        finally:
            self.client = None
            self.nodes = None

    async def read_raw_once(self, *, timeout_s: float) -> ReadOnceResult:
        """只执行 read_attributes，不做结果解析。

        Args:
            timeout_s: 单次 read_attributes 超时时间。

        Returns:
            ReadOnceResult: 原始读取结果和 read_attributes 耗时。
        """
        if self.client is None or self.nodes is None:
            return ReadOnceResult(
                ok=False,
                data_values=None,
                read_cost_ms=0.0,
            )

        started_at = time.monotonic()

        try:
            data_values = await asyncio.wait_for(
                self.client.read_attributes(self.nodes, ua.AttributeIds.Value),
                timeout=timeout_s,
            )
        except Exception:
            return ReadOnceResult(
                ok=False,
                data_values=None,
                read_cost_ms=(time.monotonic() - started_at) * 1000.0,
            )

        return ReadOnceResult(
            ok=True,
            data_values=data_values,
            read_cost_ms=(time.monotonic() - started_at) * 1000.0,
        )

    async def read_tick(
        self,
        *,
        expected_variable_count: int,
        timeout_s: float,
    ) -> TickResult:
        """执行一次完整 tick：读取 + 后处理 + 统计总耗时。

        Args:
            expected_variable_count: 期望读取到的变量数量。
            timeout_s: 单次 read_attributes 超时时间。

        Returns:
            TickResult: 单 tick 的完整诊断结果。
        """
        tick_started_at = time.monotonic()

        read_result = await self.read_raw_once(timeout_s=timeout_s)

        post_started_at = time.monotonic()
        process_result = _process_data_values(
            data_values=read_result.data_values,
            read_ok=read_result.ok,
            expected_variable_count=expected_variable_count,
        )
        post_ms = (time.monotonic() - post_started_at) * 1000.0

        tick_ms = (time.monotonic() - tick_started_at) * 1000.0

        return TickResult(
            ok=process_result.ok,
            value_count=process_result.value_count,
            server_timestamp=process_result.server_timestamp,
            read_ms=read_result.read_cost_ms,
            post_ms=post_ms,
            tick_ms=tick_ms,
            batch_mismatch=process_result.batch_mismatch,
        )


def _process_data_values(
    *,
    data_values: Sequence | None,
    read_ok: bool,
    expected_variable_count: int,
) -> ProcessResult:
    """处理 read_attributes 返回值。

    当前后处理只做最小逻辑：
    1. 判断 DataValue 是否有效；
    2. 统计有效变量数量；
    3. 提取首个变量的 ServerTimestamp；
    4. 判断变量数量是否匹配。

    Args:
        data_values: read_attributes 返回的 DataValue 列表。
        read_ok: read_attributes 是否成功。
        expected_variable_count: 期望变量数量。

    Returns:
        ProcessResult: 后处理结果。
    """
    if not read_ok or data_values is None:
        return ProcessResult(
            ok=False,
            value_count=0,
            server_timestamp=None,
            batch_mismatch=False,
        )

    value_count = sum(
        1
        for data_value in data_values
        if data_value is not None and data_value.Value is not None
    )

    server_timestamp = (
        data_values[0].ServerTimestamp
        if data_values and data_values[0] is not None
        else None
    )

    batch_mismatch = value_count != expected_variable_count

    return ProcessResult(
        ok=not batch_mismatch,
        value_count=value_count,
        server_timestamp=server_timestamp,
        batch_mismatch=batch_mismatch,
    )


def _choose_available_port(
    *,
    host: str = "127.0.0.1",
    minimum_port: int = 40001,
    maximum_port: int = 59999,
) -> int:
    """随机选择一个当前可绑定 TCP 端口。"""
    rng = random.SystemRandom()
    tried: set[int] = set()

    while True:
        candidate = rng.randint(minimum_port, maximum_port)
        if candidate in tried:
            continue

        tried.add(candidate)

        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

            try:
                sock.bind((host, candidate))
            except OSError:
                if len(tried) >= maximum_port - minimum_port + 1:
                    raise RuntimeError("No available TCP ports found in the configured range")
                continue

            return candidate


def _assign_dynamic_port(source: SimulatedSource) -> SimulatedSource:
    """复制 source，并替换为随机高位端口。"""
    assigned_port = _choose_available_port()
    return replace(
        source,
        connection=replace(
            source.connection,
            port=assigned_port,
        ),
    )


def _build_opcua_endpoint(connection: SourceConnection) -> str:
    """根据 SourceConnection 构造 OPC UA endpoint。"""
    transport = connection.transport.strip().lower()
    scheme = "opc.tcp" if transport == "tcp" else f"opc.{transport}"
    return f"{scheme}://{connection.host}:{connection.port}"


def _read_cpu_stat() -> tuple[int, int]:
    """读取 Linux /proc/stat，返回 total_ticks 和 idle_ticks。"""
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
    """周期采样整机 CPU 使用率。"""
    try:
        prev_total, prev_idle = _read_cpu_stat()
    except Exception:
        return []

    samples: list[float] = []

    while not stop_event.is_set():
        await asyncio.sleep(interval_s)

        try:
            cur_total, cur_idle = _read_cpu_stat()
        except Exception:
            break

        delta_total = cur_total - prev_total
        delta_idle = cur_idle - prev_idle
        prev_total, prev_idle = cur_total, cur_idle

        if delta_total <= 0:
            continue

        used_ratio = max(0.0, min(1.0, (delta_total - delta_idle) / delta_total))
        samples.append(used_ratio * 100.0)

    return samples


def _build_single_source_from_repository() -> SimulatedSource:
    """从数据库读取一个 OPC UA server 及其 profile 点位。"""
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
    point_count = len(point_rows)

    if not MIN_EXPECTED_POINT_COUNT <= point_count <= MAX_EXPECTED_POINT_COUNT:
        raise AssertionError(
            f"Expected {MIN_EXPECTED_POINT_COUNT}-{MAX_EXPECTED_POINT_COUNT} "
            f"profile items per server, got {point_count}"
        )

    points = tuple(
        SimulatedPoint(
            ln_name=row.ln_name,
            do_name=row.do_name,
            unit=row.unit.strip() if row.unit is not None else None,
            data_type=row.data_type,
        )
        for row in point_rows
    )

    row = current_group_rows[0]

    return SimulatedSource(
        connection=SourceConnection(
            name=(
                row.asset_code
                or row.ld_name
                or row.ied_name
                or f"source_{row.endpoint_id}"
            ).strip(),
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


def _percentile(sorted_values: Sequence[float], percentile: float) -> float:
    """计算线性插值百分位数。"""
    if not sorted_values:
        return 0.0

    if len(sorted_values) == 1:
        return sorted_values[0]

    index = (percentile / 100.0) * (len(sorted_values) - 1)
    low = int(index)
    high = min(low + 1, len(sorted_values) - 1)
    fraction = index - low

    return sorted_values[low] + fraction * (sorted_values[high] - sorted_values[low])


def _safe_mean(values: Sequence[float]) -> float:
    """安全计算均值。"""
    return statistics.mean(values) if values else 0.0


def _safe_max(values: Sequence[float]) -> float:
    """安全计算最大值。"""
    return max(values, default=0.0)


def _safe_percentile(values: Sequence[float], percentile: float) -> float:
    """安全计算百分位数。"""
    return _percentile(sorted(values), percentile) if values else 0.0


def _evaluate_client_period(
    timestamps: tuple[float, ...],
    *,
    target_hz: float,
) -> tuple[int, float, float, float]:
    """评估客户端采样周期稳定性。

    Args:
        timestamps: 每个成功 tick 的客户端完成时间，单位为 monotonic 秒。
        target_hz: 客户端目标采样频率。

    Returns:
        tuple[int, float, float, float]: 周期样本数、通过率、p95误差、p99误差。
    """
    if len(timestamps) < 2:
        return 0, 0.0, 0.0, 0.0

    expected_s = 1.0 / target_hz
    errors_ms: list[float] = []
    pass_count = 0

    for index in range(1, len(timestamps)):
        actual_s = timestamps[index] - timestamps[index - 1]
        if actual_s <= 0:
            continue

        error_ratio = abs(actual_s - expected_s) / expected_s
        errors_ms.append(abs(actual_s - expected_s) * 1000.0)

        if error_ratio <= PERIOD_TOLERANCE_RATIO:
            pass_count += 1

    if not errors_ms:
        return 0, 0.0, 0.0, 0.0

    return (
        len(errors_ms),
        pass_count / len(errors_ms),
        round(_safe_percentile(errors_ms, 95), 1),
        round(_safe_percentile(errors_ms, 99), 1),
    )


def _evaluate_server_timestamp(
    timestamps: tuple[datetime, ...],
    *,
    measured_duration_s: float,
) -> tuple[int, float, float]:
    """评估 ServerTimestamp 变化情况。

    Args:
        timestamps: 每次成功读取时采集的 ServerTimestamp。
        measured_duration_s: 测量阶段持续时间。

    Returns:
        tuple[int, float, float]: 唯一时间戳数量、观测刷新 Hz、p95 更新时间误差。
    """
    unique_timestamps: list[datetime] = []
    previous: datetime | None = None

    for timestamp in timestamps:
        if previous is None or timestamp > previous:
            unique_timestamps.append(timestamp)
            previous = timestamp

    observed_hz = len(unique_timestamps) / measured_duration_s if measured_duration_s > 0 else 0.0

    if len(unique_timestamps) < 2 or SOURCE_UPDATE_HZ <= 0:
        return len(unique_timestamps), observed_hz, 0.0

    expected_s = 1.0 / SOURCE_UPDATE_HZ
    errors_ms: list[float] = []

    for index in range(1, len(unique_timestamps)):
        actual_s = (unique_timestamps[index] - unique_timestamps[index - 1]).total_seconds()
        if actual_s <= 0:
            continue
        errors_ms.append(abs(actual_s - expected_s) * 1000.0)

    return (
        len(unique_timestamps),
        observed_hz,
        round(_safe_percentile(errors_ms, 95), 1),
    )


def _build_failure_reason(
    *,
    batch_mismatches: int,
    read_errors: int,
    missed_ratio: float,
    achieved_ratio: float,
    client_period_pass_ratio: float,
    client_period_samples: int,
) -> str:
    """根据通过条件生成失败原因。"""
    reasons: list[str] = []

    if batch_mismatches > 0:
        reasons.append(f"batch_mismatches={batch_mismatches}")

    if read_errors > 0:
        reasons.append(f"read_errors={read_errors}")

    if missed_ratio > MISSED_PASS_RATIO:
        reasons.append(f"missed_ratio={missed_ratio:.3f}>{MISSED_PASS_RATIO:.3f}")

    if achieved_ratio < ACHIEVED_PASS_RATIO:
        reasons.append(f"achieved_ratio={achieved_ratio:.3f}<{ACHIEVED_PASS_RATIO:.3f}")

    if client_period_samples <= 0:
        reasons.append("client_period_samples=0")
    elif client_period_pass_ratio < PERIOD_PASS_RATIO:
        reasons.append(
            f"client_period_pass_ratio={client_period_pass_ratio:.3f}<{PERIOD_PASS_RATIO:.3f}"
        )

    return "; ".join(reasons)


async def _variable_count(source: SimulatedSource) -> int:
    """连接 live server，确认变量可读取数量。"""
    reader = OpcUaSingleServerReader(source)
    await reader.connect()

    try:
        result = await reader.read_tick(
            expected_variable_count=len(source.points),
            timeout_s=READ_TIMEOUT_S,
        )
        return result.value_count if result.ok else 0
    finally:
        await reader.close()


async def _run_level(
    source: SimulatedSource,
    *,
    expected_variable_count: int,
    target_hz: float,
) -> LevelResult:
    """执行单 server 某一目标频率档位诊断。

    Args:
        source: 参与诊断的单个 OPC UA server。
        expected_variable_count: 每次读取期望返回的变量数量。
        target_hz: 当前目标客户端采样频率。

    Returns:
        LevelResult: 当前频率档位诊断结果。
    """
    target_interval_s = 1.0 / target_hz
    target_period_ms = 1000.0 / target_hz
    total_duration_s = WARMUP_S + LOAD_LEVEL_DURATION_S
    spike_threshold_ms = target_period_ms * SPIKE_RATIO_OF_PERIOD

    stop_event = asyncio.Event()
    cpu_task = asyncio.create_task(_sample_cpu_percent(stop_event))

    reader = OpcUaSingleServerReader(source)

    completed_ticks = 0
    failed_ticks = 0
    missed_ticks = 0
    batch_mismatches = 0
    read_errors = 0

    read_ms_values: list[float] = []
    post_ms_values: list[float] = []
    tick_ms_values: list[float] = []
    client_sample_times: list[float] = []
    server_timestamps: list[datetime] = []

    try:
        await reader.connect()

        started_at = time.monotonic()
        deadline = started_at + total_duration_s
        measure_started_at = started_at + WARMUP_S
        next_tick = started_at

        while True:
            now = time.monotonic()
            if now >= deadline:
                break

            sleep_s = next_tick - now
            if sleep_s > 0:
                await asyncio.sleep(sleep_s)

            tick_started_at = time.monotonic()
            should_measure = tick_started_at >= measure_started_at

            result = await reader.read_tick(
                expected_variable_count=expected_variable_count,
                timeout_s=READ_TIMEOUT_S,
            )

            tick_finished_at = time.monotonic()

            if should_measure:
                read_ms_values.append(result.read_ms)
                post_ms_values.append(result.post_ms)
                tick_ms_values.append(result.tick_ms)

                if result.batch_mismatch:
                    failed_ticks += 1
                    batch_mismatches += 1
                elif not result.ok:
                    failed_ticks += 1
                    read_errors += 1
                else:
                    completed_ticks += 1
                    client_sample_times.append(tick_finished_at)

                    if result.server_timestamp is not None:
                        server_timestamps.append(result.server_timestamp)

            next_tick += target_interval_s

            now = time.monotonic()
            while next_tick <= now:
                next_tick += target_interval_s
                if should_measure:
                    missed_ticks += 1

    finally:
        stop_event.set()
        await reader.close()

    cpu_samples = await cpu_task

    expected_ticks = max(1, int(LOAD_LEVEL_DURATION_S * target_hz))
    achieved_hz = completed_ticks / LOAD_LEVEL_DURATION_S
    achieved_ratio = completed_ticks / expected_ticks
    missed_ratio = missed_ticks / expected_ticks

    (
        client_period_samples,
        client_period_pass_ratio,
        client_period_p95_error_ms,
        client_period_p99_error_ms,
    ) = _evaluate_client_period(
        tuple(client_sample_times),
        target_hz=target_hz,
    )

    (
        server_timestamp_unique_count,
        server_timestamp_observed_hz,
        server_timestamp_period_p95_error_ms,
    ) = _evaluate_server_timestamp(
        tuple(server_timestamps),
        measured_duration_s=LOAD_LEVEL_DURATION_S,
    )

    read_spike_count = sum(1 for item in read_ms_values if item > spike_threshold_ms)
    post_spike_count = sum(1 for item in post_ms_values if item > spike_threshold_ms)
    tick_spike_count = sum(1 for item in tick_ms_values if item > spike_threshold_ms)

    failure_reason = _build_failure_reason(
        batch_mismatches=batch_mismatches,
        read_errors=read_errors,
        missed_ratio=missed_ratio,
        achieved_ratio=achieved_ratio,
        client_period_pass_ratio=client_period_pass_ratio,
        client_period_samples=client_period_samples,
    )

    passed = failure_reason == ""

    return LevelResult(
        target_hz=target_hz,
        target_period_ms=target_period_ms,
        expected_variable_count=expected_variable_count,
        expected_ticks=expected_ticks,
        completed_ticks=completed_ticks,
        failed_ticks=failed_ticks,
        missed_ticks=missed_ticks,
        missed_ratio=missed_ratio,
        achieved_hz=achieved_hz,
        achieved_ratio=achieved_ratio,
        read_mean_ms=round(_safe_mean(read_ms_values), 1),
        read_p50_ms=round(_safe_percentile(read_ms_values, 50), 1),
        read_p95_ms=round(_safe_percentile(read_ms_values, 95), 1),
        read_p99_ms=round(_safe_percentile(read_ms_values, 99), 1),
        read_max_ms=round(_safe_max(read_ms_values), 1),
        read_spike_count=read_spike_count,
        post_mean_ms=round(_safe_mean(post_ms_values), 3),
        post_p50_ms=round(_safe_percentile(post_ms_values, 50), 3),
        post_p95_ms=round(_safe_percentile(post_ms_values, 95), 3),
        post_p99_ms=round(_safe_percentile(post_ms_values, 99), 3),
        post_max_ms=round(_safe_max(post_ms_values), 3),
        post_spike_count=post_spike_count,
        tick_mean_ms=round(_safe_mean(tick_ms_values), 1),
        tick_p50_ms=round(_safe_percentile(tick_ms_values, 50), 1),
        tick_p95_ms=round(_safe_percentile(tick_ms_values, 95), 1),
        tick_p99_ms=round(_safe_percentile(tick_ms_values, 99), 1),
        tick_max_ms=round(_safe_max(tick_ms_values), 1),
        tick_spike_count=tick_spike_count,
        client_period_samples=client_period_samples,
        client_period_pass_ratio=client_period_pass_ratio,
        client_period_p95_error_ms=client_period_p95_error_ms,
        client_period_p99_error_ms=client_period_p99_error_ms,
        server_timestamp_unique_count=server_timestamp_unique_count,
        server_timestamp_observed_hz=server_timestamp_observed_hz,
        server_timestamp_period_p95_error_ms=server_timestamp_period_p95_error_ms,
        batch_mismatches=batch_mismatches,
        read_errors=read_errors,
        cpu_mean_percent=round(_safe_mean(cpu_samples), 1),
        cpu_peak_percent=round(_safe_max(cpu_samples), 1),
        passed=passed,
        failure_reason=failure_reason,
    )


async def _run_frequency_ramp(
    source: SimulatedSource,
    *,
    expected_variable_count: int,
) -> RampResult:
    """从 HZ_START 开始自动升频，直到首次失败。"""
    target_hz = HZ_START
    max_pass_hz: float | None = None
    levels: list[LevelResult] = []

    while target_hz <= HZ_MAX:
        result = await _run_level(
            source,
            expected_variable_count=expected_variable_count,
            target_hz=target_hz,
        )
        levels.append(result)

        _print_level_result(result)

        if not result.passed:
            break

        max_pass_hz = target_hz
        target_hz += HZ_STEP

    return RampResult(
        max_pass_hz=max_pass_hz,
        levels=tuple(levels),
    )


def _print_level_result(result: LevelResult) -> None:
    """打印单个频率档位结果。"""
    status = "PASS" if result.passed else "FAIL"

    print()
    print(
        f"[hz={result.target_hz:.1f} | period={result.target_period_ms:.1f}ms | {status}]"
    )
    print(
        "  ticks: "
        f"exp={result.expected_ticks}, "
        f"done={result.completed_ticks}, "
        f"failed={result.failed_ticks}, "
        f"miss={result.missed_ticks}, "
        f"miss_ratio={result.missed_ratio:.3f}, "
        f"ach={result.achieved_ratio:.3f}, "
        f"ach_hz={result.achieved_hz:.2f}"
    )
    print(
        "  read_ms: "
        f"mean={result.read_mean_ms:.1f}, "
        f"p50={result.read_p50_ms:.1f}, "
        f"p95={result.read_p95_ms:.1f}, "
        f"p99={result.read_p99_ms:.1f}, "
        f"max={result.read_max_ms:.1f}, "
        f"spikes={result.read_spike_count}"
    )
    print(
        "  post_ms: "
        f"mean={result.post_mean_ms:.3f}, "
        f"p50={result.post_p50_ms:.3f}, "
        f"p95={result.post_p95_ms:.3f}, "
        f"p99={result.post_p99_ms:.3f}, "
        f"max={result.post_max_ms:.3f}, "
        f"spikes={result.post_spike_count}"
    )
    print(
        "  tick_ms: "
        f"mean={result.tick_mean_ms:.1f}, "
        f"p50={result.tick_p50_ms:.1f}, "
        f"p95={result.tick_p95_ms:.1f}, "
        f"p99={result.tick_p99_ms:.1f}, "
        f"max={result.tick_max_ms:.1f}, "
        f"spikes={result.tick_spike_count}"
    )
    print(
        "  client_period: "
        f"samples={result.client_period_samples}, "
        f"pass={result.client_period_pass_ratio:.3f}, "
        f"p95err={result.client_period_p95_error_ms:.1f}ms, "
        f"p99err={result.client_period_p99_error_ms:.1f}ms"
    )
    print(
        "  server_ts: "
        f"unique={result.server_timestamp_unique_count}, "
        f"observed_hz={result.server_timestamp_observed_hz:.2f}, "
        f"p95err={result.server_timestamp_period_p95_error_ms:.1f}ms"
    )
    print(
        "  errors: "
        f"mismatch={result.batch_mismatches}, "
        f"read_errors={result.read_errors}, "
        f"cpu_mean={result.cpu_mean_percent:.1f}%, "
        f"cpu_peak={result.cpu_peak_percent:.1f}%"
    )

    if result.failure_reason:
        print(f"  failure_reason: {result.failure_reason}")


def _print_summary(
    ramp_result: RampResult,
    *,
    source: SimulatedSource,
    assigned_port: int,
) -> None:
    """打印单 server 自动升频诊断汇总。"""
    print()
    print("=" * 132)
    print("  source_simulation 单 server OPC UA 最大可用频率诊断结果")
    print("=" * 132)
    print(f"  endpoint={_build_opcua_endpoint(source.connection)}")
    print(f"  assigned_port={assigned_port}")
    print(f"  vars/server={ramp_result.levels[0].expected_variable_count if ramp_result.levels else 0}")
    print(f"  warmup={WARMUP_S:.1f}s")
    print(f"  measure_duration={LOAD_LEVEL_DURATION_S:.1f}s")
    print(f"  hz_start={HZ_START:.1f}")
    print(f"  hz_step={HZ_STEP:.1f}")
    print(f"  hz_max={HZ_MAX:.1f}")
    print(f"  source_update_enabled={SOURCE_UPDATE_ENABLED}")
    print(f"  source_update_hz={SOURCE_UPDATE_HZ:.1f}")
    print(f"  period_tolerance={PERIOD_TOLERANCE_RATIO:.2f}")
    print(f"  period_pass_ratio={PERIOD_PASS_RATIO:.2f}")
    print(f"  achieved_pass_ratio={ACHIEVED_PASS_RATIO:.2f}")
    print(f"  missed_pass_ratio={MISSED_PASS_RATIO:.2f}")
    print(f"  spike_threshold={SPIKE_RATIO_OF_PERIOD:.2f} * target_period")
    print()

    max_pass = f"{ramp_result.max_pass_hz:.1f}Hz" if ramp_result.max_pass_hz is not None else "N/A"
    print(f"  max_pass_hz={max_pass}")
    print()

    header = (
        f"  {'hz':>6} "
        f"{'period':>8} "
        f"{'done':>6} "
        f"{'miss%':>7} "
        f"{'ach':>6} "
        f"{'r95':>7} "
        f"{'r99':>7} "
        f"{'rmax':>7} "
        f"{'rspk':>5} "
        f"{'p95':>7} "
        f"{'p99':>7} "
        f"{'t95':>7} "
        f"{'t99':>7} "
        f"{'tmax':>7} "
        f"{'tspk':>5} "
        f"{'cli_p':>6} "
        f"{'cli99':>7} "
        f"{'cpu':>6} "
        f"{'status':>7}"
    )
    print(header)

    for level in ramp_result.levels:
        status = "PASS" if level.passed else "FAIL"
        print(
            f"  {level.target_hz:>6.1f} "
            f"{level.target_period_ms:>8.1f} "
            f"{level.completed_ticks:>6} "
            f"{level.missed_ratio * 100:>7.2f} "
            f"{level.achieved_ratio:>6.3f} "
            f"{level.read_p95_ms:>7.1f} "
            f"{level.read_p99_ms:>7.1f} "
            f"{level.read_max_ms:>7.1f} "
            f"{level.read_spike_count:>5} "
            f"{level.post_p95_ms:>7.3f} "
            f"{level.post_p99_ms:>7.3f} "
            f"{level.tick_p95_ms:>7.1f} "
            f"{level.tick_p99_ms:>7.1f} "
            f"{level.tick_max_ms:>7.1f} "
            f"{level.tick_spike_count:>5} "
            f"{level.client_period_pass_ratio:>6.3f} "
            f"{level.client_period_p99_error_ms:>7.1f} "
            f"{level.cpu_mean_percent:>6.1f} "
            f"{status:>7}"
        )

    print()
    print("  关键列说明：")
    print("  hz      : 当前目标客户端采样频率，单位 Hz。")
    print("  period  : 目标采样周期，period = 1000 / hz，单位 ms。")
    print("  done    : 测量阶段内成功完成的完整 tick 数。")
    print("  miss%   : missed tick 占 expected_ticks 的比例；用于判断是否整体跟不上周期。")
    print("  ach     : 实际完成率，ach = done / expected_ticks。")
    print("  r95/r99 : read_attributes 全量读取耗时的 p95 / p99，单位 ms。")
    print("  rmax    : read_attributes 单次最大耗时，仅用于观察尖峰，不直接判失败。")
    print("  rspk    : read_attributes 尖峰次数；超过 spike_threshold 即记一次。")
    print("  p95/p99 : 后处理耗时 post_process 的 p95 / p99，单位 ms。")
    print("  t95/t99 : 完整 tick 耗时的 p95 / p99，tick = read + post + 其他少量开销。")
    print("  tmax    : 完整 tick 最大耗时，仅用于观察异常尖峰。")
    print("  tspk    : 完整 tick 尖峰次数。")
    print("  cli_p   : 客户端相邻 tick 周期落入容差范围的比例。")
    print("  cli99   : 客户端采样周期误差的 p99，单位 ms。")
    print("  cpu     : 测量阶段整机平均 CPU 使用率。")
    print("  status  : 当前频率档位是否通过。")
    print("=" * 132)
    print()


@contextmanager
def _load_test_context() -> Iterator[LoadTestContext]:
    """启动单个 simulator server，并生成诊断上下文。"""
    source = _build_single_source_from_repository()
    source = _assign_dynamic_port(source)

    point_count = len(source.points)
    assigned_port = source.connection.port

    interval_seconds = 1.0 / SOURCE_UPDATE_HZ if SOURCE_UPDATE_HZ > 0 else 1.0

    fleet = SourceSimulatorFleet.create(
        sources=(source,),
        update_config=UpdateConfig(
            enabled=SOURCE_UPDATE_ENABLED,
            interval_seconds=interval_seconds,
            update_count=point_count,
        ),
    )

    with fleet:
        live_count = asyncio.run(_variable_count(source))
        assert live_count >= point_count - 5, (
            f"Expected at least {point_count - 5} live variables, got {live_count}"
        )

        yield LoadTestContext(
            source=source,
            expected_variable_count=point_count,
            assigned_port=assigned_port,
        )


@pytest.mark.load
def test_source_simulation_single_server_bottleneck() -> None:
    """自动推进到单个 OPC UA simulator server 的最大可用采样频率。"""
    with _load_test_context() as context:
        ramp_result = asyncio.run(
            _run_frequency_ramp(
                context.source,
                expected_variable_count=context.expected_variable_count,
            )
        )

        _print_summary(
            ramp_result,
            source=context.source,
            assigned_port=context.assigned_port,
        )

    assert ramp_result.max_pass_hz is not None, "No passing frequency level found"

    first_level = ramp_result.levels[0]
    assert first_level.passed, (
        f"Baseline {HZ_START:.1f}Hz failed: {first_level.failure_reason}"
    )