"""source_simulation OPC UA 仿真服务器采样能力负载测试。

本测试用于评估 source_simulation 在不同 server 数量、不同客户端采样频率下的
可持续读取能力上限。

设计原则：
1. 每个 server 使用一个 asyncua Client 长连接，避免反复连接造成测试噪声；
2. 单个 server 内部使用一次 read_attributes 批量读取全部变量；
3. 多个 server 之间使用 asyncio.gather 并发读取，避免客户端串行循环成为瓶颈；
4. 客户端采样周期使用 time.monotonic() 统计；
5. ServerTimestamp 只作为服务端数据刷新情况的辅助指标，不用于判断客户端采样周期；
6. 周期调度采用绝对时间推进，读取超期时跳过积压 tick，并统计 missed_ticks；
7. 每个 server_count 下，从 HZ_START 开始递增 target_hz，直到首次失败。

运行示例：
    SOURCE_SIM_LOAD_LEVEL_DURATION_S=6 \
    SOURCE_SIM_LOAD_WARMUP_S=5 \
    SOURCE_SIM_LOAD_SERVER_STEP=2 \
    SOURCE_SIM_LOAD_HZ_START=1 \
    SOURCE_SIM_LOAD_HZ_STEP=2 \
    python -m pytest tests/performance/load/test_source_simulation_load.py -s -v
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

LOAD_LEVEL_DURATION_S = float(os.environ.get("SOURCE_SIM_LOAD_LEVEL_DURATION_S", "10"))
WARMUP_S = float(os.environ.get("SOURCE_SIM_LOAD_WARMUP_S", "5"))

PERIOD_TOLERANCE_RATIO = float(os.environ.get("SOURCE_SIM_LOAD_PERIOD_TOLERANCE_RATIO", "0.2"))
PERIOD_PASS_RATIO = float(os.environ.get("SOURCE_SIM_LOAD_PERIOD_PASS_RATIO", "0.90"))
ACHIEVED_PASS_RATIO = float(os.environ.get("SOURCE_SIM_LOAD_ACHIEVED_PASS_RATIO", "0.90"))
MIN_PERIOD_SAMPLES = int(os.environ.get("SOURCE_SIM_LOAD_MIN_PERIOD_SAMPLES", "3"))

SOURCE_UPDATE_HZ = float(os.environ.get("SOURCE_SIM_LOAD_SOURCE_UPDATE_HZ", "10"))
SOURCE_UPDATE_INTERVAL_S = 1.0 / SOURCE_UPDATE_HZ

SERVER_STEP = int(os.environ.get("SOURCE_SIM_LOAD_SERVER_STEP", "2"))
HZ_START = float(os.environ.get("SOURCE_SIM_LOAD_HZ_START", "1"))
HZ_STEP = float(os.environ.get("SOURCE_SIM_LOAD_HZ_STEP", "2"))

READ_TIMEOUT_S = float(os.environ.get("SOURCE_SIM_LOAD_READ_TIMEOUT_S", "5"))


@dataclass(frozen=True, slots=True)
class ServerReadResult:
    """单个 server 单次批量读取结果。"""

    ok: bool
    value_count: int
    server_timestamp: datetime | None


@dataclass(frozen=True, slots=True)
class LevelResult:
    """一个 server_count + target_hz 档位的测试结果。"""

    server_count: int
    target_hz: float
    expected_variable_count: int

    expected_ticks: int
    completed_ticks: int
    missed_ticks_total: int
    batch_mismatches_total: int
    read_errors_total: int

    achieved_hz: float
    achieved_ratio: float

    client_period_samples: int
    client_period_pass_ratio: float
    client_period_p95_error_ms: float

    server_period_samples: int
    server_period_pass_ratio: float
    server_period_p95_error_ms: float

    cpu_mean_percent: float
    cpu_peak_percent: float

    passed: bool


@dataclass(frozen=True, slots=True)
class ServerRampSummary:
    """一个 server_count 下的频率递增测试摘要。"""

    server_count: int
    max_pass_hz: float | None
    levels: tuple[LevelResult, ...]


@dataclass(frozen=True, slots=True)
class LoadTestContext:
    """整轮负载测试共享上下文。"""

    servers: tuple[SimulatedSource, ...]
    expected_variable_count: int
    assigned_ports: tuple[int, ...]


@dataclass(slots=True)
class OpcUaServerReader:
    """单个 OPC UA server 的长连接批量读取器。"""

    source: SimulatedSource
    client: Client | None = None
    nodes: list | None = None

    async def connect(self) -> None:
        """建立 OPC UA 长连接，并缓存本 server 的所有变量节点。"""
        self.client = Client(url=_build_opcua_endpoint(self.source.connection))
        await self.client.__aenter__()

        namespace_uri = str(self.source.connection.namespace_uri)
        ns_idx = await self.client.get_namespace_index(namespace_uri)

        self.nodes = [
            self.client.get_node(f"ns={ns_idx};s={logical_path(self.source.connection, point)}")
            for point in self.source.points
        ]

    async def close(self) -> None:
        """关闭 OPC UA 连接。"""
        if self.client is None:
            return

        try:
            await self.client.__aexit__(None, None, None)
        finally:
            self.client = None
            self.nodes = None

    async def read_once(self, *, timeout_s: float) -> ServerReadResult:
        """批量读取本 server 的全部变量。

        Args:
            timeout_s: 单个 server 一次批量读取的超时时间。

        Returns:
            ServerReadResult: 本次读取是否成功、有效变量数量、首个变量的 ServerTimestamp。
        """
        if self.client is None or self.nodes is None:
            return ServerReadResult(ok=False, value_count=0, server_timestamp=None)

        try:
            data_values = await asyncio.wait_for(
                self.client.read_attributes(self.nodes, ua.AttributeIds.Value),
                timeout=timeout_s,
            )
        except Exception:
            return ServerReadResult(ok=False, value_count=0, server_timestamp=None)

        value_count = sum(
            1 for data_value in data_values if data_value is not None and data_value.Value is not None
        )
        server_timestamp = (
            data_values[0].ServerTimestamp
            if data_values and data_values[0] is not None
            else None
        )

        return ServerReadResult(
            ok=True,
            value_count=value_count,
            server_timestamp=server_timestamp,
        )


def _choose_available_ports(
    count: int,
    *,
    host: str = "127.0.0.1",
    minimum_port: int = 40001,
    maximum_port: int = 59999,
) -> tuple[int, ...]:
    """随机选择一组当前可绑定的 TCP 端口。"""
    if count <= 0:
        return ()

    ports: list[int] = []
    reservations: list[socket.socket] = []
    tried: set[int] = set()
    rng = random.SystemRandom()

    try:
        while len(ports) < count:
            candidate = rng.randint(minimum_port, maximum_port)
            if candidate in tried:
                continue

            tried.add(candidate)
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

            try:
                sock.bind((host, candidate))
            except OSError:
                sock.close()
                if len(tried) >= maximum_port - minimum_port + 1:
                    raise RuntimeError("No available TCP ports found in the configured range")
                continue

            reservations.append(sock)
            ports.append(candidate)

        return tuple(ports)
    finally:
        for sock in reservations:
            sock.close()


def _assign_dynamic_ports(sources: tuple[SimulatedSource, ...]) -> tuple[SimulatedSource, ...]:
    """复制 source 配置，并替换为随机高位端口，避免旧进程端口冲突。"""
    assigned_ports = _choose_available_ports(len(sources))
    return tuple(
        replace(source, connection=replace(source.connection, port=assigned_ports[index]))
        for index, source in enumerate(sources)
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
    """周期采样主机 CPU 使用率。"""
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


def _build_sources_from_repository() -> tuple[SimulatedSource, ...]:
    """从数据库读取同一 OPC UA profile 分组下的 server 和点位。"""
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
    if not 300 <= point_count <= 500:
        raise AssertionError(f"Expected ~400 profile items per server, got {point_count}")

    points = tuple(
        SimulatedPoint(
            ln_name=row.ln_name,
            do_name=row.do_name,
            unit=row.unit.strip() if row.unit is not None else None,
            data_type=row.data_type,
        )
        for row in point_rows
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
    """连接一个 live server，确认变量节点可读取数量。"""
    reader = OpcUaServerReader(source)
    await reader.connect()

    try:
        result = await reader.read_once(timeout_s=READ_TIMEOUT_S)
        return result.value_count if result.ok else 0
    finally:
        await reader.close()


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


def _evaluate_monotonic_period(
    timestamps: tuple[float, ...],
    *,
    target_hz: float,
) -> tuple[int, float, float]:
    """基于客户端 monotonic 时间评估采样周期稳定性。

    Args:
        timestamps: 客户端完成一次全量 tick 后记录的 monotonic 时间。
        target_hz: 目标客户端采样频率。

    Returns:
        tuple[int, float, float]: 周期样本数、周期通过率、p95 周期误差毫秒。
    """
    if len(timestamps) < 2:
        return 0, 0.0, 0.0

    expected_s = 1.0 / target_hz
    errors: list[float] = []
    pass_count = 0

    for index in range(1, len(timestamps)):
        actual_s = timestamps[index] - timestamps[index - 1]
        if actual_s <= 0:
            continue

        error_ratio = abs(actual_s - expected_s) / expected_s
        errors.append(error_ratio)

        if error_ratio <= PERIOD_TOLERANCE_RATIO:
            pass_count += 1

    if not errors:
        return 0, 0.0, 0.0

    sorted_errors = sorted(errors)
    p95_error_ms = _percentile(sorted_errors, 95) * expected_s * 1000.0

    return len(errors), pass_count / len(errors), round(p95_error_ms, 1)


def _evaluate_server_timestamp_period(
    timestamps: tuple[datetime, ...],
    *,
    source_update_hz: float,
) -> tuple[int, float, float]:
    """基于 ServerTimestamp 评估服务端数据刷新周期。

    注意：
    客户端采样频率可能高于服务端刷新频率，因此 ServerTimestamp 可能重复。
    本函数会先去重，只评估服务端时间戳发生变化时的间隔。

    Args:
        timestamps: 从 DataValue.ServerTimestamp 采集到的时间戳。
        source_update_hz: 仿真服务端目标刷新频率。

    Returns:
        tuple[int, float, float]: 周期样本数、周期通过率、p95 周期误差毫秒。
    """
    unique_timestamps: list[datetime] = []
    previous: datetime | None = None

    for timestamp in timestamps:
        if previous is None or timestamp > previous:
            unique_timestamps.append(timestamp)
            previous = timestamp

    if len(unique_timestamps) < 2:
        return 0, 0.0, 0.0

    expected_s = 1.0 / source_update_hz
    errors: list[float] = []
    pass_count = 0

    for index in range(1, len(unique_timestamps)):
        actual_s = (unique_timestamps[index] - unique_timestamps[index - 1]).total_seconds()
        if actual_s <= 0:
            continue

        error_ratio = abs(actual_s - expected_s) / expected_s
        errors.append(error_ratio)

        if error_ratio <= PERIOD_TOLERANCE_RATIO:
            pass_count += 1

    if not errors:
        return 0, 0.0, 0.0

    sorted_errors = sorted(errors)
    p95_error_ms = _percentile(sorted_errors, 95) * expected_s * 1000.0

    return len(errors), pass_count / len(errors), round(p95_error_ms, 1)


async def _connect_readers(servers: tuple[SimulatedSource, ...]) -> tuple[OpcUaServerReader, ...]:
    """并发建立多个 OPC UA server reader。"""
    readers = tuple(OpcUaServerReader(server) for server in servers)
    await asyncio.gather(*(reader.connect() for reader in readers))
    return readers


async def _close_readers(readers: tuple[OpcUaServerReader, ...]) -> None:
    """关闭全部 OPC UA reader。"""
    await asyncio.gather(*(reader.close() for reader in readers), return_exceptions=True)


async def _read_all_servers_once(
    readers: tuple[OpcUaServerReader, ...],
) -> tuple[ServerReadResult, ...]:
    """并发读取全部 server，每个 server 内部只做一次批量读取。"""
    return tuple(
        await asyncio.gather(
            *(reader.read_once(timeout_s=READ_TIMEOUT_S) for reader in readers),
            return_exceptions=False,
        )
    )


async def _run_level(
    servers: tuple[SimulatedSource, ...],
    *,
    expected_variable_count: int,
    target_hz: float,
) -> LevelResult:
    """执行一个 server_count + target_hz 档位测试。

    Args:
        servers: 当前档位参与测试的 server。
        expected_variable_count: 每个 server 期望读取到的变量数。
        target_hz: 客户端目标采样频率。

    Returns:
        LevelResult: 当前档位的完整统计结果。
    """
    target_interval_s = 1.0 / target_hz
    duration_s = WARMUP_S + LOAD_LEVEL_DURATION_S

    stop_event = asyncio.Event()
    cpu_task = asyncio.create_task(_sample_cpu_percent(stop_event))

    readers: tuple[OpcUaServerReader, ...] = ()

    completed_ticks = 0
    missed_ticks_total = 0
    batch_mismatches = 0
    read_errors = 0

    client_sample_times: list[float] = []
    server_timestamps: list[datetime] = []

    try:
        readers = await _connect_readers(servers)

        started_at = time.monotonic()
        deadline = started_at + duration_s
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

            results = await _read_all_servers_once(readers)

            tick_ok = True
            tick_server_timestamp: datetime | None = None

            for result in results:
                if not result.ok:
                    tick_ok = False
                    if should_measure:
                        read_errors += 1
                    continue

                if should_measure and result.value_count != expected_variable_count:
                    batch_mismatches += 1

                if tick_server_timestamp is None and result.server_timestamp is not None:
                    tick_server_timestamp = result.server_timestamp

            if should_measure and tick_ok:
                completed_ticks += 1
                client_sample_times.append(time.monotonic())

                if tick_server_timestamp is not None:
                    server_timestamps.append(tick_server_timestamp)

            next_tick += target_interval_s

            now = time.monotonic()
            while next_tick <= now:
                next_tick += target_interval_s
                if should_measure:
                    missed_ticks_total += 1

    finally:
        stop_event.set()

        if readers:
            await _close_readers(readers)

    cpu_samples = await cpu_task

    expected_ticks = max(1, int(LOAD_LEVEL_DURATION_S * target_hz))
    achieved_hz = completed_ticks / LOAD_LEVEL_DURATION_S
    achieved_ratio = completed_ticks / expected_ticks

    client_period_samples, client_period_pass_ratio, client_period_p95_error_ms = (
        _evaluate_monotonic_period(
            tuple(client_sample_times),
            target_hz=target_hz,
        )
    )

    server_period_samples, server_period_pass_ratio, server_period_p95_error_ms = (
        _evaluate_server_timestamp_period(
            tuple(server_timestamps),
            source_update_hz=SOURCE_UPDATE_HZ,
        )
    )

    cpu_mean_percent = statistics.mean(cpu_samples) if cpu_samples else 0.0
    cpu_peak_percent = max(cpu_samples, default=0.0)

    passed = (
        batch_mismatches == 0
        and read_errors == 0
        and achieved_ratio >= ACHIEVED_PASS_RATIO
        and client_period_samples >= MIN_PERIOD_SAMPLES
        and client_period_pass_ratio >= PERIOD_PASS_RATIO
    )

    return LevelResult(
        server_count=len(servers),
        target_hz=target_hz,
        expected_variable_count=expected_variable_count,
        expected_ticks=expected_ticks,
        completed_ticks=completed_ticks,
        missed_ticks_total=missed_ticks_total,
        batch_mismatches_total=batch_mismatches,
        read_errors_total=read_errors,
        achieved_hz=achieved_hz,
        achieved_ratio=achieved_ratio,
        client_period_samples=client_period_samples,
        client_period_pass_ratio=client_period_pass_ratio,
        client_period_p95_error_ms=client_period_p95_error_ms,
        server_period_samples=server_period_samples,
        server_period_pass_ratio=server_period_pass_ratio,
        server_period_p95_error_ms=server_period_p95_error_ms,
        cpu_mean_percent=cpu_mean_percent,
        cpu_peak_percent=cpu_peak_percent,
        passed=passed,
    )


async def _run_server_level(
    context: LoadTestContext,
    *,
    server_count: int,
) -> ServerRampSummary:
    """对一个 server_count 执行 target_hz 递增测试，直到首次失败。"""
    servers = context.servers[:server_count]
    levels: list[LevelResult] = []

    target_hz = HZ_START
    max_pass_hz: float | None = None

    while True:
        result = await _run_level(
            servers,
            expected_variable_count=context.expected_variable_count,
            target_hz=target_hz,
        )

        levels.append(result)

        if not result.passed:
            break

        max_pass_hz = target_hz
        target_hz += HZ_STEP

    return ServerRampSummary(
        server_count=server_count,
        max_pass_hz=max_pass_hz,
        levels=tuple(levels),
    )


def _print_results(
    results: tuple[ServerRampSummary, ...],
    *,
    assigned_ports: tuple[int, ...],
) -> None:
    """打印负载测试摘要和每个档位明细。"""
    vars_per_server = results[0].levels[0].expected_variable_count if results else 0
    port_range = (
        f"{assigned_ports[0]}-{assigned_ports[-1]}"
        if assigned_ports
        else "N/A"
    )

    print()
    print("=" * 80)
    print("  source_simulation OPC UA 采样能力负载测试结果")
    print("=" * 80)
    print(
        f"  vars/server={vars_per_server}  "
        f"source_update={SOURCE_UPDATE_HZ:.1f}Hz  "
        f"warmup={WARMUP_S:.1f}s  "
        f"measure_duration={LOAD_LEVEL_DURATION_S:.1f}s"
    )
    print(
        f"  hz_start={HZ_START:.1f}  "
        f"hz_step={HZ_STEP:.1f}  "
        f"period_tolerance={PERIOD_TOLERANCE_RATIO:.2f}  "
        f"period_pass_ratio={PERIOD_PASS_RATIO:.2f}  "
        f"achieved_pass_ratio={ACHIEVED_PASS_RATIO:.2f}"
    )
    print(f"  assigned_ports: {len(assigned_ports)} ports ({port_range})")
    print()

    print(f"  {'servers':>7}  {'limit_hz':>8}")
    print(f"  {'-------':>7}  {'--------':>8}")
    for summary in results:
        limit = f"{summary.max_pass_hz:.1f}" if summary.max_pass_hz is not None else "N/A"
        print(f"  {summary.server_count:>7}  {limit:>8}")

    print()

    header = (
        f"  {'hz':>5}  "
        f"{'exp':>5}  "
        f"{'done':>5}  "
        f"{'miss':>5}  "
        f"{'ach%':>6}  "
        f"{'cli_p':>6}  "
        f"{'cli_p95':>8}  "
        f"{'srv_p':>6}  "
        f"{'srv_p95':>8}  "
        f"{'mismatch':>8}  "
        f"{'errors':>6}  "
        f"{'cpu%':>5}  "
        f"{'status':>6}"
    )

    for summary in results:
        print(f"  --- servers={summary.server_count} limit={summary.max_pass_hz} ---")
        print(header)

        for level in summary.levels:
            status = "PASS" if level.passed else "FAIL"
            print(
                f"  {level.target_hz:>5.1f}  "
                f"{level.expected_ticks:>5}  "
                f"{level.completed_ticks:>5}  "
                f"{level.missed_ticks_total:>5}  "
                f"{level.achieved_ratio * 100:>6.1f}  "
                f"{level.client_period_pass_ratio:>6.3f}  "
                f"{level.client_period_p95_error_ms:>8.1f}  "
                f"{level.server_period_pass_ratio:>6.3f}  "
                f"{level.server_period_p95_error_ms:>8.1f}  "
                f"{level.batch_mismatches_total:>8}  "
                f"{level.read_errors_total:>6}  "
                f"{level.cpu_mean_percent:>5.1f}  "
                f"{status:>6}"
            )

        print()


@contextmanager
def _load_test_context() -> Iterator[LoadTestContext]:
    """启动完整 simulator fleet，并生成负载测试上下文。"""
    all_sources = _build_sources_from_repository()
    if len(all_sources) < 2:
        raise AssertionError(f"Need at least 2 servers, got {len(all_sources)}")

    selected_servers = _assign_dynamic_ports(all_sources)
    assigned_ports = tuple(server.connection.port for server in selected_servers)
    point_count = len(selected_servers[0].points)

    fleet = SourceSimulatorFleet.create(
        sources=selected_servers,
        update_config=UpdateConfig(
            enabled=True,
            interval_seconds=SOURCE_UPDATE_INTERVAL_S,
            update_count=point_count,
        ),
    )

    with fleet:
        live_count = asyncio.run(_variable_count(selected_servers[0]))
        assert live_count >= point_count - 5, (
            f"Expected at least {point_count - 5} live variables, got {live_count}"
        )

        yield LoadTestContext(
            servers=selected_servers,
            expected_variable_count=point_count,
            assigned_ports=assigned_ports,
        )


@pytest.mark.load
def test_source_simulation_sampling_capacity_limit() -> None:
    """测试 source_simulation 在不同 server 数量下的客户端采样能力上限。"""
    with _load_test_context() as context:
        total_servers = len(context.servers)
        server_ramp = tuple(range(1, total_servers + 1, SERVER_STEP))

        print(f"Total servers available: {total_servers}")
        print(f"Server ramp: {server_ramp}")
        print(f"Hz ramp: start={HZ_START}, step={HZ_STEP}")

        results: list[ServerRampSummary] = []

        for server_count in server_ramp:
            summary = asyncio.run(
                _run_server_level(
                    context,
                    server_count=server_count,
                )
            )
            results.append(summary)

        assigned_ports = context.assigned_ports

    _print_results(
        tuple(results),
        assigned_ports=assigned_ports,
    )

    for summary in results:
        first_level = summary.levels[0]
        assert first_level.passed, (
            f"Baseline {HZ_START:.0f}Hz failed for server_count={summary.server_count}"
        )