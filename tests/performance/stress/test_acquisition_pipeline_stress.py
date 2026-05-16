r"""OPC UA 采集链路压力测试。

运行方式：
    docker compose -f docker-compose.ingest-dev.yaml up -d

    LOAD_TARGET=acquisition LOAD_MODE=polling python -m pytest tests/performance/stress/test_acquisition_pipeline_stress.py -s
    LOAD_TARGET=acquisition LOAD_MODE=subscribe python -m pytest tests/performance/stress/test_acquisition_pipeline_stress.py -s
    LOAD_TARGET=publish python -m pytest tests/performance/stress/test_acquisition_pipeline_stress.py -s
    LOAD_TARGET=e2e LOAD_MODE=polling python -m pytest tests/performance/stress/test_acquisition_pipeline_stress.py -s
    LOAD_TARGET=e2e LOAD_MODE=subscribe python -m pytest tests/performance/stress/test_acquisition_pipeline_stress.py -s

环境变量：
    LOAD_TARGET                acquisition|publish|e2e，默认 acquisition
    LOAD_MODE                  polling|subscribe，默认 polling（仅在 acquisition/e2e 时有效）
    LOAD_RAMP                  逗号分隔的设备数，默认 1,5,10
    LOAD_LEVEL_DURATION_S      每个压力层级持续秒数，默认 30
    LOAD_WARMUP_S              OPC UA 仿真服务启动后的预热秒数，默认 5
    LOAD_KAFKA_DRAIN_S         每轮结束后 Kafka 消费补偿秒数，默认 3
    LOAD_EXPECTED_PERIOD_MS    期望采集周期，默认 1000ms
    LOAD_GAP_FACTOR            周期异常倍数，默认 2.5
    LOAD_PROFILE_TOP_N         cProfile 展示数量，默认 15
    LOAD_OUTPUT_DIR            报告输出目录，默认 tests/tmp
"""

from __future__ import annotations

import asyncio
import cProfile
import json
import os
import pstats
import statistics
import subprocess
import sys
import threading
import time
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from io import StringIO
from pathlib import Path
from typing import Any

_PROJECT_ROOT = Path(__file__).resolve().parents[3]
_SRC_ROOT = _PROJECT_ROOT / "src"
for _path in (str(_PROJECT_ROOT), str(_SRC_ROOT)):
    if _path not in sys.path:
        sys.path.insert(0, _path)

import pytest
import redis as redis_module
from kafka import KafkaConsumer
from sqlalchemy import text

try:
    from tools.source_lab.opcua_sim.fleet_runtime import OpcUaFleetRuntime
except ModuleNotFoundError:  # pragma: no cover - legacy runtime removed in source_lab refactor
    pytest.skip(
        "Legacy OpcUaFleetRuntime is not available in the current source_lab layout",
        allow_module_level=True,
    )
from whale.ingest.adapters.config.opcua_source_acquisition_definition_repository import (
    OpcUaSourceAcquisitionDefinitionRepository,
)
from whale.ingest.adapters.config.source_runtime_config_repository import (
    SourceRuntimeConfigRepository,
)
from whale.ingest.adapters.message.kafka_message_publisher import KafkaMessagePublisher
from whale.ingest.adapters.source.opcua_source_acquisition_adapter import (
    OpcUaSourceAcquisitionAdapter,
)
from whale.ingest.adapters.source.static_source_acquisition_port_registry import (
    StaticSourceAcquisitionPortRegistry,
)
from whale.ingest.adapters.state.redis_source_state_cache import (
    RedisSourceStateCache,
    RedisSourceStateCacheSettings,
)
from whale.ingest.config import KafkaMessageConfig
from whale.ingest.usecases.build_runtime_plan_usecase import RuntimePlanBuildUseCase
from whale.ingest.usecases.dtos.source_acquisition_execution_plan import (
    SourceAcquisitionExecutionPlan,
)
from whale.ingest.usecases.emit_state_snapshot_usecase import EmitStateSnapshotUseCase
from whale.ingest.usecases.execute_source_acquisition_usecase import (
    ExecuteSourceAcquisitionUseCase,
)
from whale.ingest.usecases.subscribe_source_state_usecase import (
    SubscribeSourceStateUseCase,
)
from whale.shared.persistence.init_db import init_db
from whale.shared.persistence.orm import AcquisitionTask
from whale.shared.persistence.session import engine as shared_engine
from whale.shared.persistence.session import session_scope
from whale.shared.persistence.template.sample_data import generate_all_sample_data


# ─────────────────────────────────────────────────────────────────────
# 基础配置
# ─────────────────────────────────────────────────────────────────────

LOAD_TARGET = os.environ.get("LOAD_TARGET", "acquisition")
LOAD_MODE = os.environ.get("LOAD_MODE", "polling")
LEVEL_DURATION_S = int(os.environ.get("LOAD_LEVEL_DURATION_S", "30"))
WARMUP_S = int(os.environ.get("LOAD_WARMUP_S", "5"))
KAFKA_DRAIN_S = float(os.environ.get("LOAD_KAFKA_DRAIN_S", "3"))
EXPECTED_PERIOD_MS = float(os.environ.get("LOAD_EXPECTED_PERIOD_MS", "1000"))
GAP_FACTOR = float(os.environ.get("LOAD_GAP_FACTOR", "2.5"))
PROFILE_TOP_N = int(os.environ.get("LOAD_PROFILE_TOP_N", "15"))
OUTPUT_DIR = Path(os.environ.get("LOAD_OUTPUT_DIR", "tests/tmp"))

KAFKA_BS = "127.0.0.1:9092"
STATION_ID = f"LOAD-{uuid.uuid4().hex[:6]}"
TOPIC = f"whale.ingest.load.{uuid.uuid4().hex[:6]}"
HASH_KEY = f"whale:load:{uuid.uuid4().hex[:6]}"

SERVER_TIME_FIELDS = (
    "source_observed_at",
    "server_sent_at",
    "server_timestamp",
    "source_timestamp",
    "opcua_server_timestamp",
    "observed_at",
    "received_at",
    "timestamp",
)
FALLBACK_SERVER_TIME_FIELDS = {"observed_at", "received_at", "timestamp"}


# ─────────────────────────────────────────────────────────────────────
# Pipeline 依赖 dataclass
# ─────────────────────────────────────────────────────────────────────


@dataclass
class PipelineDeps:
    """采集链路依赖对象容器。"""

    config_repo: SourceRuntimeConfigRepository
    definition_repo: OpcUaSourceAcquisitionDefinitionRepository
    plan_build_usecase: RuntimePlanBuildUseCase
    registry: StaticSourceAcquisitionPortRegistry
    state_cache: RedisSourceStateCache
    emit_usecase: EmitStateSnapshotUseCase


# ─────────────────────────────────────────────────────────────────────
# 通用统计函数
# ─────────────────────────────────────────────────────────────────────


def _percentile(sorted_values: list[float], q: float) -> float:
    """计算百分位数，输入必须已经排序。"""
    if not sorted_values:
        raise ValueError("sorted_values 不能为空")
    if len(sorted_values) == 1:
        return sorted_values[0]

    pos = (len(sorted_values) - 1) * q
    lo = int(pos)
    hi = min(lo + 1, len(sorted_values) - 1)
    weight = pos - lo
    return sorted_values[lo] * (1 - weight) + sorted_values[hi] * weight


def _summary(values: list[float]) -> dict[str, float | int | None]:
    """生成 count/min/p50/p90/p95/p99/max/mean/stdev 统计。"""
    if not values:
        return {
            "count": 0,
            "min": None,
            "p50": None,
            "p90": None,
            "p95": None,
            "p99": None,
            "max": None,
            "mean": None,
            "stdev": None,
        }

    sorted_values = sorted(values)
    return {
        "count": len(sorted_values),
        "min": sorted_values[0],
        "p50": _percentile(sorted_values, 0.50),
        "p90": _percentile(sorted_values, 0.90),
        "p95": _percentile(sorted_values, 0.95),
        "p99": _percentile(sorted_values, 0.99),
        "max": sorted_values[-1],
        "mean": statistics.mean(sorted_values),
        "stdev": statistics.stdev(sorted_values) if len(sorted_values) >= 2 else 0.0,
    }


def _fmt_ms(value: Any) -> str:
    return f"{value:.1f}ms" if isinstance(value, (int, float)) else "—"


def _fmt_rate(value: Any) -> str:
    return f"{value:.2f}" if isinstance(value, (int, float)) else "—"


def _fmt_seconds(value: Any) -> str:
    return f"{value:.3f}s" if isinstance(value, (int, float)) else "—"


def _short_func(item: dict[str, Any] | None) -> str:
    if not item:
        return "—"
    file_name = Path(str(item.get("file", ""))).name
    func = str(item.get("func", ""))
    line = item.get("line", "")
    return f"{file_name}:{line}:{func}"[:90]


def _summary_row(name: str, stat: dict[str, Any]) -> str:
    return (
        "| "
        f"{name} | "
        f"{stat.get('count', 0)} | "
        f"{_fmt_ms(stat.get('min'))} | "
        f"{_fmt_ms(stat.get('p50'))} | "
        f"{_fmt_ms(stat.get('p90'))} | "
        f"{_fmt_ms(stat.get('p95'))} | "
        f"{_fmt_ms(stat.get('p99'))} | "
        f"{_fmt_ms(stat.get('max'))} | "
        f"{_fmt_ms(stat.get('mean'))} | "
        f"{_fmt_ms(stat.get('stdev'))} |"
    )


# ─────────────────────────────────────────────────────────────────────
# 时间字段解析
# ─────────────────────────────────────────────────────────────────────


def _parse_dt(value: Any) -> datetime | None:
    """解析时间字段，并统一转换为 UTC aware datetime。"""
    if value is None:
        return None

    if isinstance(value, datetime):
        return value.astimezone(UTC) if value.tzinfo else value.replace(tzinfo=UTC)

    if isinstance(value, (int, float)):
        try:
            return datetime.fromtimestamp(value, tz=UTC)
        except (OSError, OverflowError, ValueError):
            return None

    if isinstance(value, str):
        text_value = value.strip()
        if not text_value:
            return None
        if text_value.endswith("Z"):
            text_value = text_value[:-1] + "+00:00"
        try:
            dt = datetime.fromisoformat(text_value)
        except ValueError:
            return None
        return dt.astimezone(UTC) if dt.tzinfo else dt.replace(tzinfo=UTC)

    return None


def _extract_server_time(state: dict[str, Any]) -> tuple[datetime | None, str | None, bool]:
    """从 state 中提取 server 发送时间。"""
    for field in SERVER_TIME_FIELDS:
        dt = _parse_dt(state.get(field))
        if dt is not None:
            return dt, field, field in FALLBACK_SERVER_TIME_FIELDS
    return None, None, False


def _series_key(state: dict[str, Any]) -> str | None:
    """构造一个稳定的测点序列 key，用于周期统计。"""
    candidates = (
        ("device_code", "variable_key"),
        ("source_id", "node_id"),
        ("source_id", "signal_id"),
        ("source_id", "variable_key"),
        ("runtime_config_id", "node_id"),
        ("task_id", "node_id"),
        ("node_id",),
        ("signal_id",),
        ("variable_key",),
        ("path",),
        ("name",),
    )

    for fields in candidates:
        parts = []
        for field in fields:
            value = state.get(field)
            if value is None:
                break
            parts.append(str(value))
        if len(parts) == len(fields):
            return ":".join(parts)

    return None


# ─────────────────────────────────────────────────────────────────────
# Kafka 消息捕获
# ─────────────────────────────────────────────────────────────────────


class KafkaCapture:
    """在单轮压力测试期间持续捕获 Kafka 消息。"""

    def __init__(self, topic: str, bootstrap_servers: str, group_id: str) -> None:
        self._topic = topic
        self._bootstrap_servers = bootstrap_servers
        self._group_id = group_id
        self._stop_event = threading.Event()
        self._ready_event = threading.Event()
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self._records: list[dict[str, Any]] = []
        self._errors: list[str] = []
        self._ignored_count = 0
        self._invalid_json_count = 0

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

        if not self._ready_event.wait(timeout=10):
            raise RuntimeError("KafkaCapture 在 10 秒内未完成初始化")

    def stop(self, drain_s: float) -> dict[str, Any]:
        if drain_s > 0:
            time.sleep(drain_s)

        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=5)

        with self._lock:
            return {
                "records": list(self._records),
                "errors": list(self._errors),
                "ignored_count": self._ignored_count,
                "invalid_json_count": self._invalid_json_count,
            }

    def _run(self) -> None:
        consumer: KafkaConsumer | None = None

        try:
            consumer = KafkaConsumer(
                self._topic,
                bootstrap_servers=self._bootstrap_servers,
                auto_offset_reset="latest",
                enable_auto_commit=False,
                group_id=self._group_id,
                consumer_timeout_ms=100,
            )

            deadline = time.time() + 10
            while not consumer.assignment() and time.time() < deadline:
                consumer.poll(timeout_ms=100)

            if consumer.assignment():
                consumer.seek_to_end()

            self._ready_event.set()

            while not self._stop_event.is_set():
                polled = consumer.poll(timeout_ms=200)
                for _topic_partition, messages in polled.items():
                    for msg in messages:
                        self._handle_message(msg)

        except Exception as exc:
            with self._lock:
                self._errors.append(str(exc))
            self._ready_event.set()

        finally:
            if consumer is not None:
                try:
                    consumer.close()
                except Exception:
                    pass

    def _handle_message(self, msg: Any) -> None:
        receive_ns = time.time_ns()

        try:
            body = json.loads(msg.value.decode("utf-8"))
        except Exception:
            with self._lock:
                self._invalid_json_count += 1
            return

        if body.get("message_type") != "STATE_SNAPSHOT":
            with self._lock:
                self._ignored_count += 1
            return

        record = {
            "receive_wall_time_ns": receive_ns,
            "receive_wall_time": datetime.fromtimestamp(receive_ns / 1e9, tz=UTC),
            "kafka_timestamp_ms": msg.timestamp,
            "kafka_timestamp_type": msg.timestamp_type,
            "topic": msg.topic,
            "partition": msg.partition,
            "offset": msg.offset,
            "body": body,
        }

        with self._lock:
            self._records.append(record)


# ─────────────────────────────────────────────────────────────────────
# cProfile 分析
# ─────────────────────────────────────────────────────────────────────


def _profile_summary(profile: cProfile.Profile, top_n: int) -> dict[str, Any]:
    stats = pstats.Stats(profile)
    raw_stats = stats.stats

    cumtime_items = sorted(raw_stats.items(), key=lambda item: -item[1][3])[:top_n]
    tottime_items = sorted(raw_stats.items(), key=lambda item: -item[1][2])[:top_n]

    def convert(items: list[Any]) -> list[dict[str, Any]]:
        result = []
        for rank, ((file_name, line, func), (_cc, ncalls, tottime, cumtime, _callers)) in enumerate(
            items,
            start=1,
        ):
            result.append(
                {
                    "rank": rank,
                    "file": file_name,
                    "line": line,
                    "func": func,
                    "ncalls": ncalls,
                    "tottime": tottime,
                    "cumtime": cumtime,
                }
            )
        return result

    module_bucket: dict[str, dict[str, float | int]] = {}
    for (file_name, _line, _func), (_cc, ncalls, tottime, cumtime, _callers) in raw_stats.items():
        module_name = _module_name(file_name)
        bucket = module_bucket.setdefault(
            module_name,
            {"cumtime": 0.0, "tottime": 0.0, "calls": 0},
        )
        bucket["cumtime"] = float(bucket["cumtime"]) + cumtime
        bucket["tottime"] = float(bucket["tottime"]) + tottime
        bucket["calls"] = int(bucket["calls"]) + ncalls

    module_top = sorted(
        module_bucket.items(),
        key=lambda item: -float(item[1]["cumtime"]),
    )[:top_n]

    cumtime_text = StringIO()
    tottime_text = StringIO()
    pstats.Stats(profile, stream=cumtime_text).sort_stats("cumtime").print_stats(top_n)
    pstats.Stats(profile, stream=tottime_text).sort_stats("tottime").print_stats(top_n)

    return {
        "cumtime_top": convert(cumtime_items),
        "tottime_top": convert(tottime_items),
        "module_top": [
            {
                "module": name,
                "cumtime": value["cumtime"],
                "tottime": value["tottime"],
                "calls": value["calls"],
            }
            for name, value in module_top
        ],
        "cumtime_text": cumtime_text.getvalue(),
        "tottime_text": tottime_text.getvalue(),
    }


def _module_name(file_name: str) -> str:
    normalized = file_name.replace("\\", "/")

    if "/src/" in normalized:
        return normalized.split("/src/", 1)[1].removesuffix(".py")

    if "/site-packages/" in normalized:
        return normalized.split("/site-packages/", 1)[1].removesuffix(".py")

    return Path(file_name).name.removesuffix(".py")


# ─────────────────────────────────────────────────────────────────────
# 指标分析
# ─────────────────────────────────────────────────────────────────────


def _analyze_acquisition_result(
    *,
    mode: str,
    n: int,
    duration_s: float,
    runner: dict[str, Any],
    cache_state_count: int,
    expected_state_count: int,
    profile: dict[str, Any],
) -> dict[str, Any]:
    """分析 acquisition 压测结果，不依赖 Kafka 消息。"""
    execute_ms = runner.get("execute_ms", {})

    meta: dict[str, Any] = {
        "mode": mode,
        "n": n,
        "duration_s": duration_s,
        "runner": runner,
        "cache_state_count": cache_state_count,
        "expected_state_count": expected_state_count,
        "cache_fill_ratio": (
            cache_state_count / max(expected_state_count, 1)
        ),
        "profile": profile,
    }

    if mode == "polling":
        loops = runner.get("loops", 0)
        meta["loops"] = loops
        meta["execute_ms"] = execute_ms
        meta["success_count"] = runner.get("success_count", 0)
        meta["failed_count"] = runner.get("failed_count", 0)
        meta["empty_count"] = runner.get("empty_count", 0)
        meta["states_per_s"] = cache_state_count / max(duration_s, 0.001)
        meta["cycle_overrun_count"] = runner.get("cycle_overrun_count", 0)
        meta["cycle_overrun_ratio"] = runner.get("cycle_overrun_ratio", 0.0)
        meta["effective_loop_rate"] = loops / max(duration_s, 0.001)
        meta["errors"] = runner.get("errors_topn", [])
    else:
        meta["thread_alive_after_join"] = runner.get("thread_alive_after_join", False)
        meta["errors"] = runner.get("errors", [])
        meta["states_per_s"] = cache_state_count / max(duration_s, 0.001)

    return meta


def _analyze_kafka_snapshot_records(
    *,
    records: list[dict[str, Any]],
    mode: str,
    n: int,
    duration_s: float,
    runner: dict[str, Any],
    profile: dict[str, Any],
    capture_meta: dict[str, Any],
) -> dict[str, Any]:
    """分析 Kafka STATE_SNAPSHOT 消息，生成延迟、周期、吞吐和异常指标。"""
    latencies: list[float] = []
    periods: list[float] = []
    kafka_lags: list[float] = []
    publish_latencies: list[float] = []
    series_times: dict[str, list[datetime]] = {}
    series_latencies: dict[str, list[float]] = {}
    field_counts: dict[str, int] = {}

    state_count = 0
    invalid_time_count = 0
    unknown_key_count = 0
    fallback_count = 0
    negative_latency_count = 0

    items_per_msg: list[int] = []

    for record in records:
        receive_dt = record["receive_wall_time"]
        body = record["body"]
        items = body.get("items", body.get("states", []))
        if not isinstance(items, list):
            continue

        items_per_msg.append(len(items))

        kafka_timestamp_ms = record.get("kafka_timestamp_ms")
        if isinstance(kafka_timestamp_ms, int) and kafka_timestamp_ms > 0:
            kafka_lags.append(record["receive_wall_time_ns"] / 1e6 - kafka_timestamp_ms)

        snapshot_at = _parse_dt(body.get("snapshot_at"))

        for state in items:
            if not isinstance(state, dict):
                continue

            state_count += 1
            server_dt, server_field, is_fallback = _extract_server_time(state)

            if server_field is not None:
                field_counts[server_field] = field_counts.get(server_field, 0) + 1

            if is_fallback:
                fallback_count += 1

            if server_dt is None:
                invalid_time_count += 1
                continue

            latency_ms = (receive_dt - server_dt).total_seconds() * 1000
            if latency_ms < -1000:
                negative_latency_count += 1

            latencies.append(latency_ms)

            if snapshot_at is not None:
                publish_latencies.append((receive_dt - snapshot_at).total_seconds() * 1000)

            key = _series_key(state)
            if key is None:
                unknown_key_count += 1
                continue

            series_times.setdefault(key, []).append(server_dt)
            series_latencies.setdefault(key, []).append(latency_ms)

    gap_count = 0
    gap_keys = 0
    per_series_periods: dict[str, list[float]] = {}
    gap_threshold_ms = EXPECTED_PERIOD_MS * GAP_FACTOR

    for key, values in series_times.items():
        ordered = sorted(set(values))
        key_periods: list[float] = []

        for idx in range(1, len(ordered)):
            interval_ms = (ordered[idx] - ordered[idx - 1]).total_seconds() * 1000
            if interval_ms <= 0:
                continue

            periods.append(interval_ms)
            key_periods.append(interval_ms)

        key_gap_count = sum(1 for value in key_periods if value > gap_threshold_ms)
        if key_gap_count:
            gap_count += key_gap_count
            gap_keys += 1

        per_series_periods[key] = key_periods

    latency_summary = _summary(latencies)
    period_summary = _summary(periods)
    kafka_lag_summary = _summary(kafka_lags)
    publish_latency_summary = _summary(publish_latencies)

    top_slow_series = _top_slow_series(series_latencies)
    top_unstable_series = _top_unstable_series(per_series_periods, gap_threshold_ms)

    return {
        "mode": mode,
        "n": n,
        "duration_s": duration_s,
        "messages": len(records),
        "states": state_count,
        "latency_ms": latency_summary,
        "period_ms": period_summary,
        "kafka_receive_lag_ms": kafka_lag_summary,
        "publish_latency_ms": publish_latency_summary,
        "throughput": {
            "messages_per_s": len(records) / max(duration_s, 0.001),
            "states_per_s": state_count / max(duration_s, 0.001),
            "unique_series": len(series_times),
            "avg_states_per_message": state_count / max(len(records), 1),
            "items_per_msg_min": min(items_per_msg) if items_per_msg else 0,
            "items_per_msg_max": max(items_per_msg) if items_per_msg else 0,
        },
        "gaps": {
            "count": gap_count,
            "keys": gap_keys,
            "threshold_ms": gap_threshold_ms,
        },
        "server_time_field_counts": field_counts,
        "server_time_fallback_count": fallback_count,
        "invalid_time_count": invalid_time_count,
        "unknown_key_count": unknown_key_count,
        "negative_latency_count": negative_latency_count,
        "top_slow_series": top_slow_series,
        "top_unstable_series": top_unstable_series,
        "runner": runner,
        "profile": profile,
        "capture": {
            "errors": capture_meta.get("errors", []),
            "ignored_count": capture_meta.get("ignored_count", 0),
            "invalid_json_count": capture_meta.get("invalid_json_count", 0),
        },
    }


def _top_slow_series(series_latencies: dict[str, list[float]]) -> list[dict[str, Any]]:
    rows = []
    for key, values in series_latencies.items():
        stat = _summary(values)
        rows.append(
            {
                "key": key,
                "samples": stat["count"],
                "p50": stat["p50"],
                "p95": stat["p95"],
                "max": stat["max"],
            }
        )

    return sorted(rows, key=lambda row: -(row["p95"] or 0))[:10]


def _top_unstable_series(
    per_series_periods: dict[str, list[float]],
    gap_threshold_ms: float,
) -> list[dict[str, Any]]:
    rows = []
    for key, values in per_series_periods.items():
        stat = _summary(values)
        gaps = sum(1 for value in values if value > gap_threshold_ms)
        rows.append(
            {
                "key": key,
                "intervals": stat["count"],
                "p50": stat["p50"],
                "p95": stat["p95"],
                "max": stat["max"],
                "stdev": stat["stdev"],
                "gaps": gaps,
            }
        )

    return sorted(rows, key=lambda row: (-row["gaps"], -(row["p95"] or 0)))[:10]


# ─────────────────────────────────────────────────────────────────────
# 报告生成 — acquisition
# ─────────────────────────────────────────────────────────────────────


def _write_acquisition_report(mode: str, ramp: list[int], level_metrics: list[dict[str, Any]]) -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    report_path = OUTPUT_DIR / f"acquisition_stress_{mode}.md"

    lines: list[str] = []

    lines += [
        "# OPC UA 采集刷新压力测试报告",
        "",
        "## 测试配置",
        "",
        f"- 目标：`acquisition`",
        f"- 模式：`{mode}`",
        f"- 设备数：`{ramp}`",
        f"- 持续：`{LEVEL_DURATION_S}s`",
        f"- 期望周期：`{EXPECTED_PERIOD_MS:.1f}ms`",
        f"- 生成时间：`{datetime.now(tz=UTC).strftime('%Y-%m-%d %H:%M:%S UTC')}`",
        "",
        "> 延迟口径：本报告不测 Kafka 延迟，只测采集执行耗时和 Redis latest-state 刷新结果。",
    ]

    if mode == "polling":
        lines.append("> 周期口径：统计 execute_ms 与 cycle overrun。")
    else:
        lines.append("> 周期口径：统计最终 cache 填充情况和订阅运行错误。")

    lines += ["", ""]

    if level_metrics:
        lines += _report_acquisition_level_table(level_metrics)

    lines += _report_acquisition_details(level_metrics)
    lines += _report_profile_trend(level_metrics)
    lines += _report_profile_details(level_metrics)

    report_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"\nReport → {report_path}")


def _report_acquisition_level_table(level_metrics: list[dict[str, Any]]) -> list[str]:
    lines = [
        "## 1. Level 对比",
        "",
    ]

    if level_metrics and level_metrics[0].get("mode") == "polling":
        lines += [
            "| n | loops | success | failed | empty | cache | expected | fill% | states/s | exec P50 | exec P95 | overrun | overrun% | eff rate |",
            "|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
        ]
        for m in level_metrics:
            exec_ms = m.get("execute_ms", {})
            lines.append(
                "| "
                f"{m['n']} | "
                f"{m.get('loops', 0)} | "
                f"{m.get('success_count', 0)} | "
                f"{m.get('failed_count', 0)} | "
                f"{m.get('empty_count', 0)} | "
                f"{m.get('cache_state_count', 0)} | "
                f"{m.get('expected_state_count', 0)} | "
                f"{_fmt_rate(m.get('cache_fill_ratio', 0) * 100)}% | "
                f"{_fmt_rate(m.get('states_per_s', 0))} | "
                f"{_fmt_ms(exec_ms.get('p50'))} | "
                f"{_fmt_ms(exec_ms.get('p95'))} | "
                f"{m.get('cycle_overrun_count', 0)} | "
                f"{_fmt_rate((m.get('cycle_overrun_ratio', 0) or 0) * 100)}% | "
                f"{_fmt_rate(m.get('effective_loop_rate', 0))} |"
            )
    else:
        lines += [
            "| n | cache | expected | fill% | states/s | thread_alive | errors |",
            "|---:|---:|---:|---:|---:|---:|---:|",
        ]
        for m in level_metrics:
            lines.append(
                "| "
                f"{m['n']} | "
                f"{m.get('cache_state_count', 0)} | "
                f"{m.get('expected_state_count', 0)} | "
                f"{_fmt_rate(m.get('cache_fill_ratio', 0) * 100)}% | "
                f"{_fmt_rate(m.get('states_per_s', 0))} | "
                f"{m.get('thread_alive_after_join', False)} | "
                f"{len(m.get('errors', []))} |"
            )

    lines += ["", ""]
    return lines


def _report_acquisition_details(level_metrics: list[dict[str, Any]]) -> list[str]:
    lines = ["## 2. 采集明细", ""]

    for m in level_metrics:
        lines.append(f"### n={m['n']}")
        lines.append("")

        if m.get("mode") == "polling":
            exec_ms = m.get("execute_ms", {})
            lines += [
                "| 指标 | count | min | p50 | p90 | p95 | p99 | max | mean | stdev |",
                "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
                _summary_row("execute_ms", exec_ms),
                "",
            ]

        errors = m.get("errors", [])
        if errors:
            lines.append(f"- 错误数：`{len(errors)}`")
            for err in errors[:10]:
                lines.append(f"  - `{str(err)[:200]}`")
            lines.append("")

    return lines


# ─────────────────────────────────────────────────────────────────────
# 报告生成 — publish
# ─────────────────────────────────────────────────────────────────────


def _write_publish_report(ramp: list[int], level_metrics: list[dict[str, Any]]) -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    report_path = OUTPUT_DIR / "snapshot_publish_stress.md"

    lines: list[str] = []

    lines += [
        "# latest-state snapshot 发布压力测试报告",
        "",
        "## 测试配置",
        "",
        f"- 设备数：`{ramp}`",
        f"- 持续：`{LEVEL_DURATION_S}s`",
        f"- 期望周期：`{EXPECTED_PERIOD_MS:.1f}ms`",
        f"- Kafka Topic：`{TOPIC}`",
        f"- 生成时间：`{datetime.now(tz=UTC).strftime('%Y-%m-%d %H:%M:%S UTC')}`",
        "",
        "> 延迟口径：Kafka consumer 收到 STATE_SNAPSHOT 的本机时间 - snapshot_at。",
        "> 本报告不包含 OPC UA 采集耗时。",
        "",
    ]

    if level_metrics:
        lines += _report_publish_level_table(level_metrics)

    lines += _report_latency_details(level_metrics, include_kafka_lag=True)
    lines += _report_period_details(level_metrics)
    lines += _report_profile_trend(level_metrics)
    lines += _report_profile_details(level_metrics)

    report_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"\nReport → {report_path}")


def _report_publish_level_table(level_metrics: list[dict[str, Any]]) -> list[str]:
    lines = [
        "## 1. Level 对比",
        "",
        "| n | publish_loops | success | failed | messages | states | msg/s | states/s | avg states/msg | items/min | items/max | kafka lag P95 | pub lat P95 |",
        "|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]

    for m in level_metrics:
        runner = m.get("runner", {})
        throughput = m.get("throughput", {})
        kafka_lag = m.get("kafka_receive_lag_ms", {})
        pub_lat = m.get("publish_latency_ms", {})

        lines.append(
            "| "
            f"{m['n']} | "
            f"{runner.get('publish_loops', 0)} | "
            f"{runner.get('publish_success_count', 0)} | "
            f"{runner.get('publish_failed_count', 0)} | "
            f"{m['messages']} | "
            f"{m['states']} | "
            f"{_fmt_rate(throughput.get('messages_per_s'))} | "
            f"{_fmt_rate(throughput.get('states_per_s'))} | "
            f"{_fmt_rate(throughput.get('avg_states_per_message'))} | "
            f"{throughput.get('items_per_msg_min', '—')} | "
            f"{throughput.get('items_per_msg_max', '—')} | "
            f"{_fmt_ms(kafka_lag.get('p95'))} | "
            f"{_fmt_ms(pub_lat.get('p95'))} |"
        )

    lines += ["", ""]
    return lines


# ─────────────────────────────────────────────────────────────────────
# 报告生成 — e2e
# ─────────────────────────────────────────────────────────────────────


def _write_e2e_report(mode: str, ramp: list[int], level_metrics: list[dict[str, Any]]) -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    report_path = OUTPUT_DIR / f"e2e_pipeline_stress_{mode}.md"

    lines: list[str] = []

    lines += [
        "# OPC UA -> latest-state -> Kafka 端到端压力测试报告",
        "",
        "## 测试配置",
        "",
        f"- 目标：`e2e`",
        f"- 模式：`{mode}`",
        f"- 设备数：`{ramp}`",
        f"- 持续：`{LEVEL_DURATION_S}s`",
        f"- 期望周期：`{EXPECTED_PERIOD_MS:.1f}ms`",
        f"- Kafka Topic：`{TOPIC}`",
        f"- Station ID：`{STATION_ID}`",
        f"- 生成时间：`{datetime.now(tz=UTC).strftime('%Y-%m-%d %H:%M:%S UTC')}`",
        "",
        "> 延迟口径：Kafka consumer 收到 STATE_SNAPSHOT 的本机时间 - state 中的 server/source 时间字段。",
        "> 周期口径：同一测点序列相邻两次 server/source 时间字段差值。",
        "",
    ]

    if level_metrics:
        lines += _report_e2e_level_table(level_metrics)

    lines += _report_latency_details(level_metrics, include_kafka_lag=True)
    lines += _report_period_details(level_metrics)
    lines += _report_profile_trend(level_metrics)
    lines += _report_profile_details(level_metrics)

    report_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"\nReport → {report_path}")


def _report_e2e_level_table(level_metrics: list[dict[str, Any]]) -> list[str]:
    lines = [
        "## 1. Level 对比",
        "",
    ]

    if level_metrics and level_metrics[0].get("mode") == "polling":
        lines += [
            "| n | messages | states | msg/s | states/s | acq P50 | pub P50 | e2e P50 | lat P95 | period P95 | kafka lag P95 | gaps |",
            "|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
        ]
        for m in level_metrics:
            runner = m.get("runner", {})
            throughput = m.get("throughput", {})
            latency = m.get("latency_ms", {})
            period = m.get("period_ms", {})
            kafka_lag = m.get("kafka_receive_lag_ms", {})

            lines.append(
                "| "
                f"{m['n']} | "
                f"{m['messages']} | "
                f"{m['states']} | "
                f"{_fmt_rate(throughput.get('messages_per_s'))} | "
                f"{_fmt_rate(throughput.get('states_per_s'))} | "
                f"{_fmt_ms(runner.get('acquisition_execute_ms', {}).get('p50') if isinstance(runner.get('acquisition_execute_ms'), dict) else None)} | "
                f"{_fmt_ms(runner.get('publish_execute_ms', {}).get('p50') if isinstance(runner.get('publish_execute_ms'), dict) else None)} | "
                f"{_fmt_ms(runner.get('e2e_cycle_ms', {}).get('p50') if isinstance(runner.get('e2e_cycle_ms'), dict) else None)} | "
                f"{_fmt_ms(latency.get('p95'))} | "
                f"{_fmt_ms(period.get('p95'))} | "
                f"{_fmt_ms(kafka_lag.get('p95'))} | "
                f"{m.get('gaps', {}).get('count', 0)} |"
            )
    else:
        lines += [
            "| n | messages | states | msg/s | states/s | pub P50 | lat P95 | period P95 | kafka lag P95 | gaps | sub errors | thread alive |",
            "|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
        ]
        for m in level_metrics:
            runner = m.get("runner", {})
            throughput = m.get("throughput", {})
            latency = m.get("latency_ms", {})
            period = m.get("period_ms", {})
            kafka_lag = m.get("kafka_receive_lag_ms", {})

            lines.append(
                "| "
                f"{m['n']} | "
                f"{m['messages']} | "
                f"{m['states']} | "
                f"{_fmt_rate(throughput.get('messages_per_s'))} | "
                f"{_fmt_rate(throughput.get('states_per_s'))} | "
                f"{_fmt_ms(runner.get('publish_execute_ms', {}).get('p50') if isinstance(runner.get('publish_execute_ms'), dict) else None)} | "
                f"{_fmt_ms(latency.get('p95'))} | "
                f"{_fmt_ms(period.get('p95'))} | "
                f"{_fmt_ms(kafka_lag.get('p95'))} | "
                f"{m.get('gaps', {}).get('count', 0)} | "
                f"{len(runner.get('subscribe_errors', []))} | "
                f"{runner.get('thread_alive_after_join', False)} |"
            )

    lines += ["", ""]
    return lines


# ─────────────────────────────────────────────────────────────────────
# 报告生成 — 共享组件
# ─────────────────────────────────────────────────────────────────────


def _report_latency_details(
    level_metrics: list[dict[str, Any]],
    include_kafka_lag: bool = False,
) -> list[str]:
    lines = ["## 延迟统计", ""]

    for m in level_metrics:
        latency = m.get("latency_ms", {})
        if not latency or latency.get("count", 0) == 0:
            continue

        kafka_lag = m.get("kafka_receive_lag_ms", {})
        pub_lat = m.get("publish_latency_ms", {})

        lines += [
            f"### n={m['n']}",
            "",
            f"- server 时间字段计数：`{m.get('server_time_field_counts', {})}`",
            f"- 替代字段计数：`{m.get('server_time_fallback_count', 0)}`",
            f"- 无法解析时间的 state：`{m.get('invalid_time_count', 0)}`",
            f"- 无法识别序列 key 的 state：`{m.get('unknown_key_count', 0)}`",
            f"- 负延迟样本数：`{m.get('negative_latency_count', 0)}`",
        ]

        if include_kafka_lag and kafka_lag.get("count", 0) > 0:
            lines.append(f"- Kafka broker 到 consumer 参考延迟 P95：`{_fmt_ms(kafka_lag.get('p95'))}`")

        if pub_lat and pub_lat.get("count", 0) > 0:
            lines.append(f"- publish latency (consumer receive - snapshot_at) P95：`{_fmt_ms(pub_lat.get('p95'))}`")

        lines += [
            "",
            "| 指标 | count | min | p50 | p90 | p95 | p99 | max | mean | stdev |",
            "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
            _summary_row("latency", latency),
            "",
        ]

        if m.get("top_slow_series"):
            lines += [
                "| 最慢序列 | samples | p50 | p95 | max |",
                "|---|---:|---:|---:|---:|",
            ]
            for row in m["top_slow_series"]:
                lines.append(
                    "| "
                    f"`{row['key'][:100]}` | "
                    f"{row['samples']} | "
                    f"{_fmt_ms(row['p50'])} | "
                    f"{_fmt_ms(row['p95'])} | "
                    f"{_fmt_ms(row['max'])} |"
                )
            lines.append("")

    return lines


def _report_period_details(level_metrics: list[dict[str, Any]]) -> list[str]:
    lines = ["## 周期统计", ""]

    for m in level_metrics:
        period = m.get("period_ms", {})
        if not period or period.get("count", 0) == 0:
            continue

        gaps = m.get("gaps", {})

        lines += [
            f"### n={m['n']}",
            "",
            f"- gap 阈值：`{_fmt_ms(gaps.get('threshold_ms', 0))}`",
            f"- gap 次数：`{gaps.get('count', 0)}`",
            f"- 出现 gap 的序列数：`{gaps.get('keys', 0)}`",
            "",
            "| 指标 | count | min | p50 | p90 | p95 | p99 | max | mean | stdev |",
            "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
            _summary_row("period", period),
            "",
        ]

        if m.get("top_unstable_series"):
            lines += [
                "| 最不稳定序列 | intervals | p50 | p95 | max | stdev | gaps |",
                "|---|---:|---:|---:|---:|---:|---:|",
            ]
            for row in m["top_unstable_series"]:
                lines.append(
                    "| "
                    f"`{row['key'][:100]}` | "
                    f"{row['intervals']} | "
                    f"{_fmt_ms(row['p50'])} | "
                    f"{_fmt_ms(row['p95'])} | "
                    f"{_fmt_ms(row['max'])} | "
                    f"{_fmt_ms(row['stdev'])} | "
                    f"{row['gaps']} |"
                )
            lines.append("")

    return lines


def _report_profile_trend(level_metrics: list[dict[str, Any]]) -> list[str]:
    lines = [
        "## cProfile 瓶颈趋势",
        "",
        "| n | cumtime 第一 | cumtime | tottime 第一 | tottime | 模块第一 | 模块 cumtime |",
        "|---:|---|---:|---|---:|---|---:|",
    ]

    for m in level_metrics:
        profile = m.get("profile")
        if not profile:
            continue

        cum_top = profile["cumtime_top"][0] if profile["cumtime_top"] else None
        tot_top = profile["tottime_top"][0] if profile["tottime_top"] else None
        mod_top = profile["module_top"][0] if profile["module_top"] else None

        lines.append(
            "| "
            f"{m['n']} | "
            f"{_short_func(cum_top)} | "
            f"{_fmt_seconds(cum_top.get('cumtime') if cum_top else None)} | "
            f"{_short_func(tot_top)} | "
            f"{_fmt_seconds(tot_top.get('tottime') if tot_top else None)} | "
            f"`{mod_top['module'][:80] if mod_top else '—'}` | "
            f"{_fmt_seconds(mod_top.get('cumtime') if mod_top else None)} |"
        )

    lines += ["", ""]
    return lines


def _report_profile_details(level_metrics: list[dict[str, Any]]) -> list[str]:
    lines = ["## cProfile 明细", ""]

    for m in level_metrics:
        profile = m.get("profile")
        if not profile:
            continue

        lines += [
            f"### n={m['n']} cumtime Top",
            "",
            "```text",
            profile["cumtime_text"].strip(),
            "```",
            "",
            f"### n={m['n']} tottime Top",
            "",
            "```text",
            profile["tottime_text"].strip(),
            "```",
            "",
            f"### n={m['n']} 模块聚合 Top",
            "",
            "| 模块 | cumtime | tottime | calls |",
            "|---|---:|---:|---:|",
        ]

        for row in profile["module_top"][:10]:
            lines.append(
                "| "
                f"`{row['module'][:100]}` | "
                f"{_fmt_seconds(row['cumtime'])} | "
                f"{_fmt_seconds(row['tottime'])} | "
                f"{row['calls']} |"
            )

        lines.append("")

    return lines


# ─────────────────────────────────────────────────────────────────────
# 外部服务与测试数据
# ─────────────────────────────────────────────────────────────────────


def _check_docker() -> bool:
    try:
        output = subprocess.check_output(
            ["docker", "ps", "--format", "{{.Names}}"],
            text=True,
            timeout=10,
        )
    except Exception as exc:
        print(f"ERROR: docker 不可用: {exc}")
        return False

    names = set(output.strip().splitlines())
    needed = {"whale-ingest-postgres", "whale-ingest-redis", "whale-ingest-kafka"}
    missing = needed - names

    if missing:
        print(f"ERROR: Docker 容器未运行: {missing}")
        print("请先执行: docker compose -f docker-compose.ingest-dev.yaml up -d")
        return False

    return True


def _wait_services(timeout: float = 30) -> None:
    deadline = time.time() + timeout

    while time.time() < deadline:
        try:
            with shared_engine.connect() as conn:
                conn.execute(text("SELECT 1"))
            break
        except Exception:
            time.sleep(1)

    redis_client = redis_module.Redis(host="127.0.0.1", port=16379, db=0)
    while time.time() < deadline:
        try:
            redis_client.ping()
            break
        except Exception:
            time.sleep(1)

    while time.time() < deadline:
        try:
            consumer = KafkaConsumer(bootstrap_servers=KAFKA_BS)
            consumer.topics()
            consumer.close()
            break
        except Exception:
            time.sleep(1)


def _start_servers(runtimes: list[Any]) -> int:
    started = 0

    for runtime in runtimes:
        try:
            runtime.start()
            if runtime._server is not None:
                started += 1
        except Exception as exc:
            print(f"    ERROR start {runtime.name}: {exc}")

    return started


def _stop_servers(runtimes: list[Any]) -> None:
    for runtime in runtimes:
        try:
            runtime.stop()
        except Exception:
            pass


def _enable_n_acq_tasks(n: int, acquisition_mode: str) -> None:
    with session_scope() as session:
        session.execute(text("UPDATE acq_task SET enabled = false"))
        session.commit()

        rows = session.execute(
            text(
                "SELECT task_id FROM acq_task "
                "WHERE enabled = false "
                "ORDER BY task_id "
                "LIMIT :n"
            ),
            {"n": n},
        ).fetchall()

        for (task_id,) in rows:
            task = session.get(AcquisitionTask, task_id)
            if task is not None:
                task.enabled = True
                task.acquisition_mode = acquisition_mode

        session.commit()


def _setup_env() -> None:
    values = {
        "WHALE_INGEST_DATABASE_BACKEND": "postgresql",
        "WHALE_INGEST_STATE_CACHE_BACKEND": "redis",
        "WHALE_INGEST_MESSAGE_BACKEND": "kafka",
        "WHALE_INGEST_DB_HOST": "127.0.0.1",
        "WHALE_INGEST_DB_PORT": "5432",
        "WHALE_INGEST_DB_NAME": "whale_ingest",
        "WHALE_INGEST_DB_USERNAME": "whale",
        "WHALE_INGEST_DB_PASSWORD": "whale",
        "WHALE_INGEST_REDIS_HOST": "127.0.0.1",
        "WHALE_INGEST_REDIS_PORT": "16379",
        "WHALE_INGEST_REDIS_DB": "0",
        "WHALE_INGEST_REDIS_STATE_HASH_KEY": HASH_KEY,
        "WHALE_INGEST_STATION_ID": STATION_ID,
        "WHALE_INGEST_KAFKA_BOOTSTRAP_SERVERS": KAFKA_BS,
        "WHALE_INGEST_KAFKA_TOPIC": TOPIC,
        "WHALE_INGEST_KAFKA_ACK_TIMEOUT_SECONDS": "30.0",
    }

    for key, value in values.items():
        os.environ[key] = value


def _parse_ramp(runtimes_count: int) -> list[int]:
    raw = os.environ.get("LOAD_RAMP", "")
    
    if not raw:
        # 默认：1Hz 到 10Hz 递增
        result = list(range(1, min(11, runtimes_count + 1)))
        return result or [1]
    
    try:
        values = [int(x.strip()) for x in raw.split(",") if x.strip()]
    except ValueError:
        # 解析失败，回到 1Hz 到 10Hz 递增
        values = list(range(1, min(11, runtimes_count + 1)))

    seen: set[int] = set()
    result: list[int] = []
    for v in sorted(values):
        if v not in seen and 1 <= v <= runtimes_count:
            seen.add(v)
            result.append(v)

    return result or [1]


# ─────────────────────────────────────────────────────────────────────
# 采集链路构造
# ─────────────────────────────────────────────────────────────────────


def _build_pipeline() -> PipelineDeps:
    state_cache = RedisSourceStateCache(
        settings=RedisSourceStateCacheSettings(
            host="127.0.0.1", port=16379, db=0,
            username=None, password=None,
            hash_key=HASH_KEY, station_id=STATION_ID,
        )
    )

    publisher = KafkaMessagePublisher(
        settings=KafkaMessageConfig(
            bootstrap_servers=(KAFKA_BS,),
            topic=TOPIC,
            ack_timeout_seconds=30.0,
        )
    )

    emit_usecase = EmitStateSnapshotUseCase(
        snapshot_reader_port=state_cache,
        publisher=publisher,
    )

    definition_repo = OpcUaSourceAcquisitionDefinitionRepository()
    config_repo = SourceRuntimeConfigRepository()
    plan_build_usecase = RuntimePlanBuildUseCase(
        runtime_config_port=config_repo,
        acquisition_definition_port=definition_repo,
    )

    registry = StaticSourceAcquisitionPortRegistry(
        {
            "opcua": OpcUaSourceAcquisitionAdapter(),
            "OPC_UA": OpcUaSourceAcquisitionAdapter(),
        }
    )

    return PipelineDeps(
        config_repo=config_repo,
        definition_repo=definition_repo,
        plan_build_usecase=plan_build_usecase,
        registry=registry,
        state_cache=state_cache,
        emit_usecase=emit_usecase,
    )


def _build_plans(
    configs: list[Any],
    deps: PipelineDeps,
) -> list[SourceAcquisitionExecutionPlan]:
    """Build executable acquisition plans for the selected runtime configs."""
    return deps.plan_build_usecase.build_plans(configs)


def _count_expected_states(configs: list[Any], deps: PipelineDeps) -> int:
    total = 0
    for config in configs:
        try:
            definition = deps.definition_repo.get_config(config)
            total += len(definition.items)
        except Exception:
            pass
    return total


def _get_cache_state_count() -> int:
    try:
        redis_client = redis_module.Redis(host="127.0.0.1", port=16379, db=0)
        return redis_client.hlen(HASH_KEY)
    except Exception:
        return 0


# ─────────────────────────────────────────────────────────────────────
# acquisition polling
# ─────────────────────────────────────────────────────────────────────


def _run_acquisition_polling_level(
    *,
    configs: list[Any],
    deps: PipelineDeps,
    cycle_ms: float,
) -> dict[str, Any]:
    plans = _build_plans(configs, deps)
    pull_usecase = ExecuteSourceAcquisitionUseCase(
        acquisition_port_registry=deps.registry,
        state_cache_port=deps.state_cache,
    )

    loop_count = 0
    success_count = 0
    failed_count = 0
    empty_count = 0
    execute_cost_ms: list[float] = []
    cycle_s = cycle_ms / 1000
    deadline = time.time() + LEVEL_DURATION_S
    overrun_count = 0
    error_topn: dict[str, int] = {}

    while time.time() < deadline:
        started_at = time.time()
        results = asyncio.run(pull_usecase.execute(plans))
        elapsed = time.time() - started_at
        execute_cost_ms.append(elapsed * 1000)

        for r in results:
            status = str(r.status) if hasattr(r, 'status') else str(r.get('status', ''))
            if status == "SUCCEEDED":
                success_count += 1
            elif status == "FAILED":
                failed_count += 1
                err = str(r.error_message) if hasattr(r, 'error_message') else str(r.get('error_message', ''))
                error_topn[err[:80]] = error_topn.get(err[:80], 0) + 1
            elif status == "EMPTY":
                empty_count += 1

        loop_count += 1
        remain = cycle_s - elapsed
        if remain > 0:
            time.sleep(remain)
        else:
            overrun_count += 1

    sorted_errors = sorted(error_topn.items(), key=lambda x: -x[1])[:10]

    return {
        "mode": "polling",
        "loops": loop_count,
        "success_count": success_count,
        "failed_count": failed_count,
        "empty_count": empty_count,
        "execute_ms": _summary(execute_cost_ms),
        "cycle_overrun_count": overrun_count,
        "cycle_overrun_ratio": overrun_count / max(loop_count, 1),
        "effective_loop_rate": loop_count / max(LEVEL_DURATION_S, 0.001),
        "errors_topn": [{"message": msg, "count": cnt} for msg, cnt in sorted_errors],
    }


# ─────────────────────────────────────────────────────────────────────
# acquisition subscribe
# ─────────────────────────────────────────────────────────────────────


def _run_acquisition_subscribe_level(
    *,
    configs: list[Any],
    deps: PipelineDeps,
) -> dict[str, Any]:
    subscribe_usecase = SubscribeSourceStateUseCase(
        acquisition_definition_port=deps.definition_repo,
        acquisition_port_registry=deps.registry,
        state_cache_port=deps.state_cache,
    )

    stop_event = threading.Event()
    errors: list[str] = []

    def run_subscriber() -> None:
        try:
            asyncio.run(subscribe_usecase.execute(tuple(configs), stop_event))
        except Exception as exc:
            errors.append(str(exc))

    thread = threading.Thread(target=run_subscriber, daemon=True)
    thread.start()

    time.sleep(LEVEL_DURATION_S)
    stop_event.set()
    thread.join(timeout=5)

    return {
        "mode": "subscribe",
        "thread_alive_after_join": thread.is_alive(),
        "errors": errors,
    }


# ─────────────────────────────────────────────────────────────────────
# publish level
# ─────────────────────────────────────────────────────────────────────


def _run_publish_level(
    *,
    n: int,
    deps: PipelineDeps,
    cycle_ms: float,
) -> dict[str, Any]:
    publish_loops = 0
    publish_success_count = 0
    publish_failed_count = 0
    execute_cost_ms: list[float] = []
    cycle_s = cycle_ms / 1000
    deadline = time.time() + LEVEL_DURATION_S

    while time.time() < deadline:
        started_at = time.time()
        try:
            result = deps.emit_usecase.execute()
            publish_loops += 1
            if hasattr(result, 'message_count') and result.message_count > 0:
                publish_success_count += 1
            else:
                publish_failed_count += 1
        except Exception:
            publish_failed_count += 1

        elapsed = time.time() - started_at
        execute_cost_ms.append(elapsed * 1000)
        remain = cycle_s - elapsed
        if remain > 0:
            time.sleep(remain)

    return {
        "publish_loops": publish_loops,
        "publish_success_count": publish_success_count,
        "publish_failed_count": publish_failed_count,
        "publish_execute_ms": _summary(execute_cost_ms),
    }


# ─────────────────────────────────────────────────────────────────────
# e2e polling
# ─────────────────────────────────────────────────────────────────────


def _run_e2e_polling_level(
    *,
    configs: list[Any],
    deps: PipelineDeps,
    cycle_ms: float,
) -> dict[str, Any]:
    plans = _build_plans(configs, deps)
    pull_usecase = ExecuteSourceAcquisitionUseCase(
        acquisition_port_registry=deps.registry,
        state_cache_port=deps.state_cache,
    )

    success_count = 0
    failed_count = 0
    acq_cost_ms: list[float] = []
    pub_cost_ms: list[float] = []
    e2e_cycle_ms: list[float] = []
    cycle_s = cycle_ms / 1000
    deadline = time.time() + LEVEL_DURATION_S

    while time.time() < deadline:
        cycle_started = time.time()

        acq_started = time.time()
        results = asyncio.run(pull_usecase.execute(plans))
        acq_elapsed = time.time() - acq_started
        acq_cost_ms.append(acq_elapsed * 1000)

        for r in results:
            status = str(r.status) if hasattr(r, 'status') else str(r.get('status', ''))
            if status == "SUCCEEDED":
                success_count += 1
            elif status == "FAILED":
                failed_count += 1

        pub_started = time.time()
        try:
            deps.emit_usecase.execute()
        except Exception:
            pass
        pub_elapsed = time.time() - pub_started
        pub_cost_ms.append(pub_elapsed * 1000)

        e2e_elapsed = time.time() - cycle_started
        e2e_cycle_ms.append(e2e_elapsed * 1000)
        remain = cycle_s - e2e_elapsed
        if remain > 0:
            time.sleep(remain)

    return {
        "mode": "polling",
        "success_count": success_count,
        "failed_count": failed_count,
        "acquisition_execute_ms": _summary(acq_cost_ms),
        "publish_execute_ms": _summary(pub_cost_ms),
        "e2e_cycle_ms": _summary(e2e_cycle_ms),
    }


# ─────────────────────────────────────────────────────────────────────
# e2e subscribe
# ─────────────────────────────────────────────────────────────────────


def _run_e2e_subscribe_level(
    *,
    configs: list[Any],
    deps: PipelineDeps,
    cycle_ms: float,
) -> dict[str, Any]:
    subscribe_usecase = SubscribeSourceStateUseCase(
        acquisition_definition_port=deps.definition_repo,
        acquisition_port_registry=deps.registry,
        state_cache_port=deps.state_cache,
    )

    stop_event = threading.Event()
    subscribe_errors: list[str] = []

    def run_subscriber() -> None:
        try:
            asyncio.run(subscribe_usecase.execute(tuple(configs), stop_event))
        except Exception as exc:
            subscribe_errors.append(str(exc))

    thread = threading.Thread(target=run_subscriber, daemon=True)
    thread.start()

    pub_cost_ms: list[float] = []
    cycle_s = cycle_ms / 1000
    deadline = time.time() + LEVEL_DURATION_S

    while time.time() < deadline:
        started_at = time.time()
        try:
            deps.emit_usecase.execute()
        except Exception:
            pass
        elapsed = time.time() - started_at
        pub_cost_ms.append(elapsed * 1000)
        remain = cycle_s - elapsed
        if remain > 0:
            time.sleep(remain)

    stop_event.set()
    thread.join(timeout=5)

    return {
        "mode": "subscribe",
        "thread_alive_after_join": thread.is_alive(),
        "subscribe_errors": subscribe_errors,
        "publish_execute_ms": _summary(pub_cost_ms),
    }


# ─────────────────────────────────────────────────────────────────────
# 预热填充 Redis（用于 publish 测试）
# ─────────────────────────────────────────────────────────────────────


def _warmup_redis_with_polling(configs: list[Any], deps: PipelineDeps, cycle_ms: float) -> int:
    """Execute polling acquisition once to warm up Redis cache, not counted in publish metrics."""
    plans = _build_plans(configs, deps)
    pull_usecase = ExecuteSourceAcquisitionUseCase(
        acquisition_port_registry=deps.registry,
        state_cache_port=deps.state_cache,
    )
    asyncio.run(pull_usecase.execute(plans))
    return _get_cache_state_count()


# ─────────────────────────────────────────────────────────────────────
# Pytest 入口
# ─────────────────────────────────────────────────────────────────────


@pytest.mark.stress
def test_acquisition_pipeline_stress() -> None:
    """执行 OPC UA 采集刷新、snapshot 发布或端到端压力测试，并输出 Markdown 报告。"""
    target = LOAD_TARGET
    if target not in {"acquisition", "publish", "e2e"}:
        raise ValueError(f"LOAD_TARGET 只能是 acquisition/publish/e2e，当前为 {target}")

    mode = LOAD_MODE
    if target != "publish" and mode not in {"polling", "subscribe"}:
        raise ValueError(f"LOAD_MODE 只能是 polling 或 subscribe，当前为 {mode}")

    if not _check_docker():
        pytest.skip("Docker 服务未运行")

    _setup_env()
    _wait_services()

    init_db(force=True)
    generate_all_sample_data()

    fleet = OpcUaFleetRuntime.from_database()
    runtimes = fleet._runtimes
    ramp = _parse_ramp(len(runtimes))

    print(f"\n{'='*60}")
    print(f"LOAD_TARGET={target}  LOAD_MODE={mode}  RAMP={ramp}")
    print(f"{'='*60}")

    try:
        started_count = _start_servers(runtimes)
        if started_count == 0:
            pytest.fail("没有任何 OPC UA 仿真服务成功启动，请检查端口是否被占用")

        time.sleep(WARMUP_S)

        deps = _build_pipeline()
        redis_client = redis_module.Redis(host="127.0.0.1", port=16379, db=0)

        if target == "acquisition":
            _run_acquisition_target(mode, ramp, runtimes, deps, redis_client)
        elif target == "publish":
            _run_publish_target(ramp, runtimes, deps, redis_client)
        elif target == "e2e":
            _run_e2e_target(mode, ramp, runtimes, deps, redis_client)

    finally:
        _stop_servers(runtimes)
        if fleet._temp_dir:
            fleet._temp_dir.cleanup()


def _run_acquisition_target(
    mode: str,
    ramp: list[int],
    runtimes: list[Any],
    deps: PipelineDeps,
    redis_client: Any,
) -> None:
    level_metrics: list[dict[str, Any]] = []
    all_configs = deps.config_repo.list_enabled()

    for n in ramp:
        try:
            redis_client.delete(HASH_KEY)
        except Exception:
            pass

        _enable_n_acq_tasks(n, "READ_ONCE" if mode == "polling" else "SUBSCRIBE")
        configs = all_configs[:n]
        expected_state_count = _count_expected_states(configs, deps)

        profile = cProfile.Profile()
        started_at = time.time()

        profile.enable()
        try:
            if mode == "polling":
                runner = _run_acquisition_polling_level(
                    configs=configs,
                    deps=deps,
                    cycle_ms=EXPECTED_PERIOD_MS,
                )
            else:
                runner = _run_acquisition_subscribe_level(
                    configs=configs,
                    deps=deps,
                )
        finally:
            profile.disable()

        duration_s = time.time() - started_at
        cache_state_count = _get_cache_state_count()
        profile_data = _profile_summary(profile, PROFILE_TOP_N)

        metric = _analyze_acquisition_result(
            mode=mode,
            n=n,
            duration_s=duration_s,
            runner=runner,
            cache_state_count=cache_state_count,
            expected_state_count=expected_state_count,
            profile=profile_data,
        )
        level_metrics.append(metric)

        print(
            "  "
            f"n={n}: "
            f"cache={cache_state_count}/{expected_state_count} "
            f"fill={_fmt_rate(metric.get('cache_fill_ratio', 0) * 100)}% "
            f"states/s={_fmt_rate(metric.get('states_per_s', 0))}"
        )

    _write_acquisition_report(mode, ramp, level_metrics)


def _run_publish_target(
    ramp: list[int],
    runtimes: list[Any],
    deps: PipelineDeps,
    redis_client: Any,
) -> None:
    level_metrics: list[dict[str, Any]] = []

    acquisition_mode = "READ_ONCE"
    all_configs = deps.config_repo.list_enabled()

    for n in ramp:
        try:
            redis_client.delete(HASH_KEY)
        except Exception:
            pass

        _enable_n_acq_tasks(n, acquisition_mode)
        configs = all_configs[:n]

        filled = _warmup_redis_with_polling(configs, deps, EXPECTED_PERIOD_MS)
        print(f"  n={n}: Redis warmup → {filled} keys")

        group_id = f"load-publish-{n:02d}-{uuid.uuid4().hex[:8]}"
        capture = KafkaCapture(TOPIC, KAFKA_BS, group_id)
        capture.start()

        profile = cProfile.Profile()
        started_at = time.time()

        profile.enable()
        try:
            runner = _run_publish_level(
                n=n,
                deps=deps,
                cycle_ms=EXPECTED_PERIOD_MS,
            )
        finally:
            profile.disable()
            capture_result = capture.stop(KAFKA_DRAIN_S)

        duration_s = time.time() - started_at
        profile_data = _profile_summary(profile, PROFILE_TOP_N)

        metric = _analyze_kafka_snapshot_records(
            records=capture_result["records"],
            mode="publish",
            n=n,
            duration_s=duration_s,
            runner=runner,
            profile=profile_data,
            capture_meta=capture_result,
        )
        level_metrics.append(metric)

        throughput = metric.get("throughput", {})
        print(
            "  "
            f"n={n}: "
            f"messages={metric['messages']} "
            f"states={metric['states']} "
            f"msg/s={_fmt_rate(throughput.get('messages_per_s'))} "
            f"states/s={_fmt_rate(throughput.get('states_per_s'))} "
            f"pub_lat_p95={_fmt_ms(metric.get('publish_latency_ms', {}).get('p95'))}"
        )

    _write_publish_report(ramp, level_metrics)


def _run_e2e_target(
    mode: str,
    ramp: list[int],
    runtimes: list[Any],
    deps: PipelineDeps,
    redis_client: Any,
) -> None:
    level_metrics: list[dict[str, Any]] = []
    all_configs = deps.config_repo.list_enabled()

    for n in ramp:
        try:
            redis_client.delete(HASH_KEY)
        except Exception:
            pass

        _enable_n_acq_tasks(n, "READ_ONCE" if mode == "polling" else "SUBSCRIBE")
        configs = all_configs[:n]

        group_id = f"load-e2e-{mode}-{n:02d}-{uuid.uuid4().hex[:8]}"
        capture = KafkaCapture(TOPIC, KAFKA_BS, group_id)
        capture.start()

        profile = cProfile.Profile()
        started_at = time.time()

        profile.enable()
        try:
            if mode == "polling":
                runner = _run_e2e_polling_level(
                    configs=configs,
                    deps=deps,
                    cycle_ms=EXPECTED_PERIOD_MS,
                )
            else:
                runner = _run_e2e_subscribe_level(
                    configs=configs,
                    deps=deps,
                    cycle_ms=EXPECTED_PERIOD_MS,
                )
        finally:
            profile.disable()
            capture_result = capture.stop(KAFKA_DRAIN_S)

        duration_s = time.time() - started_at
        profile_data = _profile_summary(profile, PROFILE_TOP_N)

        metric = _analyze_kafka_snapshot_records(
            records=capture_result["records"],
            mode=mode,
            n=n,
            duration_s=duration_s,
            runner=runner,
            profile=profile_data,
            capture_meta=capture_result,
        )
        level_metrics.append(metric)

        throughput = metric.get("throughput", {})
        print(
            "  "
            f"n={n}: "
            f"messages={metric['messages']} "
            f"states={metric['states']} "
            f"states/s={_fmt_rate(throughput.get('states_per_s'))} "
            f"lat_p95={_fmt_ms(metric.get('latency_ms', {}).get('p95'))} "
            f"period_p95={_fmt_ms(metric.get('period_ms', {}).get('p95'))} "
            f"gaps={metric.get('gaps', {}).get('count', 0)}"
        )

    _write_e2e_report(mode, ramp, level_metrics)


if __name__ == "__main__":
    """
    直接运行此文件进入调试模式。
    用法：
        python tests/performance/stress/test_acquisition_pipeline_stress.py
        
    环境变量参考：
        LOAD_TARGET: acquisition|publish|e2e (default: acquisition)
        LOAD_MODE: polling|subscribe (default: polling)
        LOAD_RAMP: 逗号分隔的设备数 (default: 1,5,10)
        LOAD_LEVEL_DURATION_S: 每个压力层级持续秒数 (default: 30)
    """
    import pdb
    import sys
    
    # 运行主压力测试
    try:
        test_acquisition_pipeline_stress()
    except Exception as e:
        print(f"❌ 测试异常：{e}", file=sys.stderr)
        pdb.post_mortem()
        sys.exit(1)
