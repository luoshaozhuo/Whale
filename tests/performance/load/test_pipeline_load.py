r"""OPC UA 采集链路负载测试。

运行方式：
    docker compose -f docker-compose.ingest-dev.yaml up -d
    LOAD_MODE=polling python -m pytest tests/performance/load/test_pipeline_load.py -s
    LOAD_MODE=subscribe python -m pytest tests/performance/load/test_pipeline_load.py -s

环境变量：
    LOAD_MODE                  polling|subscribe，默认 polling
    LOAD_LEVEL_DURATION_S      每个压力层级持续秒数，默认 30
    LOAD_WARMUP_S              OPC UA 仿真服务启动后的预热秒数，默认 5
    LOAD_KAFKA_DRAIN_S         每轮结束后 Kafka 消费补偿秒数，默认 3
    LOAD_EXPECTED_PERIOD_MS    期望采集周期，默认 1000ms
    LOAD_GAP_FACTOR            周期异常倍数，默认 2.5
    LOAD_LATENCY_P95_LIMIT_MS  P95 延迟疑似极限阈值，默认 2000ms
    LOAD_PERIOD_P95_FACTOR     P95 周期疑似极限倍数，默认 1.5
    LOAD_PROFILE_TOP_N         cProfile 展示数量，默认 15
    LOAD_RAMP                  压力层级，例如 "1,5,10,20"
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

from tools.opcua_sim.fleet_runtime import OpcUaFleetRuntime
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
from whale.ingest.usecases.emit_state_snapshot_usecase import EmitStateSnapshotUseCase
from whale.ingest.usecases.pull_source_state_usecase import PullSourceStateUseCase
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

LEVEL_DURATION_S = int(os.environ.get("LOAD_LEVEL_DURATION_S", "30"))
WARMUP_S = int(os.environ.get("LOAD_WARMUP_S", "5"))
KAFKA_DRAIN_S = float(os.environ.get("LOAD_KAFKA_DRAIN_S", "3"))
EXPECTED_PERIOD_MS = float(os.environ.get("LOAD_EXPECTED_PERIOD_MS", "1000"))
GAP_FACTOR = float(os.environ.get("LOAD_GAP_FACTOR", "2.5"))
LATENCY_P95_LIMIT_MS = float(os.environ.get("LOAD_LATENCY_P95_LIMIT_MS", "2000"))
PERIOD_P95_FACTOR = float(os.environ.get("LOAD_PERIOD_P95_FACTOR", "1.5"))
PROFILE_TOP_N = int(os.environ.get("LOAD_PROFILE_TOP_N", "15"))
OUTPUT_DIR = Path(os.environ.get("LOAD_OUTPUT_DIR", "tests/tmp"))

KAFKA_BS = "127.0.0.1:9092"
STATION_ID = f"LOAD-{uuid.uuid4().hex[:6]}"
TOPIC = f"whale.ingest.load.{uuid.uuid4().hex[:6]}"
HASH_KEY = f"whale:load:{uuid.uuid4().hex[:6]}"

SERVER_TIME_FIELDS = (
    "server_sent_at",
    "server_timestamp",
    "source_timestamp",
    "opcua_server_timestamp",
    "observed_at",
    "timestamp",
)
FALLBACK_SERVER_TIME_FIELDS = {"observed_at", "timestamp"}


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
    """格式化毫秒值。"""
    return f"{value:.1f}ms" if isinstance(value, (int, float)) else "—"


def _fmt_rate(value: Any) -> str:
    """格式化吞吐率。"""
    return f"{value:.2f}" if isinstance(value, (int, float)) else "—"


def _fmt_seconds(value: Any) -> str:
    """格式化秒数。"""
    return f"{value:.3f}s" if isinstance(value, (int, float)) else "—"


def _short_func(item: dict[str, Any] | None) -> str:
    """压缩 cProfile 函数名。"""
    if not item:
        return "—"
    file_name = Path(str(item.get("file", ""))).name
    func = str(item.get("func", ""))
    line = item.get("line", "")
    return f"{file_name}:{line}:{func}"[:90]


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
    """从 state 中提取 server 发送时间。

    返回：
        server_time, 字段名, 是否为替代字段

    说明：
        observed_at / timestamp 只能作为替代字段。
        严格的 server 发送时间建议后续由业务消息显式写入 server_sent_at。
    """
    for field in SERVER_TIME_FIELDS:
        dt = _parse_dt(state.get(field))
        if dt is not None:
            return dt, field, field in FALLBACK_SERVER_TIME_FIELDS
    return None, None, False


def _series_key(state: dict[str, Any]) -> str | None:
    """构造一个稳定的测点序列 key，用于周期统计。"""
    candidates = (
        ("source_id", "node_id"),
        ("source_id", "signal_id"),
        ("runtime_config_id", "node_id"),
        ("task_id", "node_id"),
        ("node_id",),
        ("signal_id",),
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
        """启动后台 Kafka 消费线程。"""
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

        if not self._ready_event.wait(timeout=10):
            raise RuntimeError("KafkaCapture 在 10 秒内未完成初始化")

    def stop(self, drain_s: float) -> dict[str, Any]:
        """等待补偿消费后停止捕获。"""
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
    """从 cProfile.Profile 中提取结构化瓶颈信息。"""
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
    """把绝对路径压缩成便于报告阅读的模块路径。"""
    normalized = file_name.replace("\\", "/")

    if "/src/" in normalized:
        return normalized.split("/src/", 1)[1].removesuffix(".py")

    if "/site-packages/" in normalized:
        return normalized.split("/site-packages/", 1)[1].removesuffix(".py")

    return Path(file_name).name.removesuffix(".py")


# ─────────────────────────────────────────────────────────────────────
# 指标分析
# ─────────────────────────────────────────────────────────────────────

def _analyze_records(
    *,
    records: list[dict[str, Any]],
    mode: str,
    n: int,
    duration_s: float,
    runner: dict[str, Any],
    profile: dict[str, Any],
    capture_meta: dict[str, Any],
) -> dict[str, Any]:
    """分析单轮 Kafka 消息，生成延迟、周期、吞吐和异常指标。"""
    latencies: list[float] = []
    periods: list[float] = []
    kafka_lags: list[float] = []
    series_times: dict[str, list[datetime]] = {}
    series_latencies: dict[str, list[float]] = {}
    field_counts: dict[str, int] = {}

    state_count = 0
    invalid_time_count = 0
    unknown_key_count = 0
    fallback_count = 0
    negative_latency_count = 0

    for record in records:
        receive_dt = record["receive_wall_time"]
        body = record["body"]
        states = body.get("states", [])
        if not isinstance(states, list):
            continue

        kafka_timestamp_ms = record.get("kafka_timestamp_ms")
        if isinstance(kafka_timestamp_ms, int) and kafka_timestamp_ms > 0:
            kafka_lags.append(record["receive_wall_time_ns"] / 1e6 - kafka_timestamp_ms)

        for state in states:
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
        "throughput": {
            "messages_per_s": len(records) / max(duration_s, 0.001),
            "states_per_s": state_count / max(duration_s, 0.001),
            "unique_series": len(series_times),
            "avg_states_per_message": state_count / max(len(records), 1),
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
    """按 P95 延迟排序，返回最慢测点序列。"""
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
    """按 gap 数和 P95 周期排序，返回周期最不稳定的测点序列。"""
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


def _infer_limit(level_metrics: list[dict[str, Any]]) -> dict[str, Any]:
    """推断首个疑似性能极限层级。"""
    previous_states_per_s: float | None = None

    for metric in level_metrics:
        n = metric["n"]
        latency_p95 = metric["latency_ms"].get("p95")
        period_p95 = metric["period_ms"].get("p95")
        gaps = metric["gaps"]["count"]
        states_per_s = metric["throughput"]["states_per_s"]

        reasons = []

        if isinstance(latency_p95, (int, float)) and latency_p95 > LATENCY_P95_LIMIT_MS:
            reasons.append(f"P95 延迟 {_fmt_ms(latency_p95)} 超过阈值 {_fmt_ms(LATENCY_P95_LIMIT_MS)}")

        period_limit = EXPECTED_PERIOD_MS * PERIOD_P95_FACTOR
        if isinstance(period_p95, (int, float)) and period_p95 > period_limit:
            reasons.append(f"P95 周期 {_fmt_ms(period_p95)} 超过阈值 {_fmt_ms(period_limit)}")

        if gaps > 0:
            reasons.append(f"出现 {gaps} 次周期 gap")

        if previous_states_per_s is not None:
            growth = states_per_s / max(previous_states_per_s, 0.001)
            if growth < 1.05 and isinstance(latency_p95, (int, float)) and latency_p95 > 500:
                reasons.append("状态吞吐增长趋缓，同时延迟上升")

        if reasons:
            return {"n": n, "reasons": reasons}

        previous_states_per_s = states_per_s

    return {"n": None, "reasons": ["未触发当前配置下的疑似极限阈值"]}


# ─────────────────────────────────────────────────────────────────────
# 报告生成
# ─────────────────────────────────────────────────────────────────────

def _write_report(mode: str, ramp: list[int], level_metrics: list[dict[str, Any]]) -> None:
    """只输出一个 Markdown 总报告。"""
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    report_path = OUTPUT_DIR / f"load_report_{mode}.md"

    lines: list[str] = []
    limit = _infer_limit(level_metrics)

    lines += [
        "# OPC UA 采集链路负载测试报告",
        "",
        "## 0. 测试配置",
        "",
        f"- 模式：`{mode}`",
        f"- 压力层级：`{ramp}`",
        f"- 每级时长：`{LEVEL_DURATION_S}s`",
        f"- 预热时长：`{WARMUP_S}s`",
        f"- Kafka 补偿消费：`{KAFKA_DRAIN_S}s`",
        f"- 期望周期：`{EXPECTED_PERIOD_MS:.1f}ms`",
        f"- gap 阈值：`{EXPECTED_PERIOD_MS * GAP_FACTOR:.1f}ms`",
        f"- P95 延迟阈值：`{LATENCY_P95_LIMIT_MS:.1f}ms`",
        f"- P95 周期阈值：`{EXPECTED_PERIOD_MS * PERIOD_P95_FACTOR:.1f}ms`",
        f"- Kafka Topic：`{TOPIC}`",
        f"- Station ID：`{STATION_ID}`",
        f"- 生成时间：`{datetime.now(tz=UTC).strftime('%Y-%m-%d %H:%M:%S UTC')}`",
        "",
        "> 延迟计算口径：`Kafka consumer 收到 STATE_SNAPSHOT 的本机时间 - state 中的 server 时间字段`。",
        "> 周期计算口径：同一测点序列相邻两次 `server 时间字段` 的差值。",
        "> 如果使用 `observed_at` 或 `timestamp`，它只是 server 发送时间的替代字段，严格口径应由业务消息显式提供 `server_sent_at`。",
        "",
        "## 1. 总览结论",
        "",
        f"- 最大测试设备数：`{max(ramp) if ramp else 0}`",
        f"- 疑似极限层级：`{limit['n'] if limit['n'] is not None else '未触发'}`",
        f"- 判断原因：{'；'.join(limit['reasons'])}",
        "",
    ]

    if level_metrics:
        best_states = max(level_metrics, key=lambda item: item["throughput"]["states_per_s"])
        worst_latency = max(
            level_metrics,
            key=lambda item: item["latency_ms"].get("p95") or -1,
        )
        worst_period = max(
            level_metrics,
            key=lambda item: item["period_ms"].get("p95") or -1,
        )

        lines += [
            f"- 最高状态吞吐：`n={best_states['n']}`，"
            f"`{_fmt_rate(best_states['throughput']['states_per_s'])} states/s`",
            f"- 最大 P95 延迟：`n={worst_latency['n']}`，"
            f"`{_fmt_ms(worst_latency['latency_ms'].get('p95'))}`",
            f"- 最大 P95 周期：`n={worst_period['n']}`，"
            f"`{_fmt_ms(worst_period['period_ms'].get('p95'))}`",
            "",
        ]

    lines += _report_level_table(level_metrics)
    lines += _report_latency_details(level_metrics)
    lines += _report_period_details(level_metrics)
    lines += _report_profile_trend(level_metrics)
    lines += _report_profile_details(level_metrics)

    report_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"\nReport → {report_path}")


def _report_level_table(level_metrics: list[dict[str, Any]]) -> list[str]:
    """生成压力层级对比表。"""
    lines = [
        "## 2. Level 对比",
        "",
        "| n | messages | states | msg/s | states/s | series | 延迟 P50 | 延迟 P95 | 延迟 Max | 周期 P50 | 周期 P95 | 周期 Max | gaps | 主要瓶颈 |",
        "|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|",
    ]

    for metric in level_metrics:
        latency = metric["latency_ms"]
        period = metric["period_ms"]
        throughput = metric["throughput"]
        profile = metric["profile"]
        top = profile["cumtime_top"][0] if profile["cumtime_top"] else None

        lines.append(
            "| "
            f"{metric['n']} | "
            f"{metric['messages']} | "
            f"{metric['states']} | "
            f"{_fmt_rate(throughput['messages_per_s'])} | "
            f"{_fmt_rate(throughput['states_per_s'])} | "
            f"{throughput['unique_series']} | "
            f"{_fmt_ms(latency.get('p50'))} | "
            f"{_fmt_ms(latency.get('p95'))} | "
            f"{_fmt_ms(latency.get('max'))} | "
            f"{_fmt_ms(period.get('p50'))} | "
            f"{_fmt_ms(period.get('p95'))} | "
            f"{_fmt_ms(period.get('max'))} | "
            f"{metric['gaps']['count']} | "
            f"{_short_func(top)} |"
        )

    lines += ["", ""]
    return lines


def _report_latency_details(level_metrics: list[dict[str, Any]]) -> list[str]:
    """生成延迟明细。"""
    lines = ["## 3. 延迟统计", ""]

    for metric in level_metrics:
        latency = metric["latency_ms"]
        kafka_lag = metric["kafka_receive_lag_ms"]

        lines += [
            f"### n={metric['n']}",
            "",
            f"- server 时间字段计数：`{metric['server_time_field_counts']}`",
            f"- 替代字段计数：`{metric['server_time_fallback_count']}`",
            f"- 无法解析时间的 state：`{metric['invalid_time_count']}`",
            f"- 无法识别序列 key 的 state：`{metric['unknown_key_count']}`",
            f"- 负延迟样本数：`{metric['negative_latency_count']}`",
            f"- Kafka broker 到 consumer 参考延迟 P95：`{_fmt_ms(kafka_lag.get('p95'))}`",
            "",
            "| 指标 | count | min | p50 | p90 | p95 | p99 | max | mean | stdev |",
            "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
            _summary_row("latency", latency),
            "",
        ]

        if metric["top_slow_series"]:
            lines += [
                "| 最慢序列 | samples | p50 | p95 | max |",
                "|---|---:|---:|---:|---:|",
            ]
            for row in metric["top_slow_series"]:
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
    """生成周期明细。"""
    lines = ["## 4. 周期统计", ""]

    for metric in level_metrics:
        period = metric["period_ms"]
        gaps = metric["gaps"]

        lines += [
            f"### n={metric['n']}",
            "",
            f"- gap 阈值：`{_fmt_ms(gaps['threshold_ms'])}`",
            f"- gap 次数：`{gaps['count']}`",
            f"- 出现 gap 的序列数：`{gaps['keys']}`",
            "",
            "| 指标 | count | min | p50 | p90 | p95 | p99 | max | mean | stdev |",
            "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
            _summary_row("period", period),
            "",
        ]

        if metric["top_unstable_series"]:
            lines += [
                "| 最不稳定序列 | intervals | p50 | p95 | max | stdev | gaps |",
                "|---|---:|---:|---:|---:|---:|---:|",
            ]
            for row in metric["top_unstable_series"]:
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
    """生成跨层级瓶颈趋势。"""
    lines = [
        "## 5. cProfile 瓶颈趋势",
        "",
        "| n | cumtime 第一 | cumtime | tottime 第一 | tottime | 模块第一 | 模块 cumtime |",
        "|---:|---|---:|---|---:|---|---:|",
    ]

    for metric in level_metrics:
        profile = metric["profile"]
        cum_top = profile["cumtime_top"][0] if profile["cumtime_top"] else None
        tot_top = profile["tottime_top"][0] if profile["tottime_top"] else None
        mod_top = profile["module_top"][0] if profile["module_top"] else None

        lines.append(
            "| "
            f"{metric['n']} | "
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
    """生成每个层级的 cProfile 详情。"""
    lines = ["## 6. cProfile 明细", ""]

    for metric in level_metrics:
        profile = metric["profile"]

        lines += [
            f"### n={metric['n']} cumtime Top",
            "",
            "```text",
            profile["cumtime_text"].strip(),
            "```",
            "",
            f"### n={metric['n']} tottime Top",
            "",
            "```text",
            profile["tottime_text"].strip(),
            "```",
            "",
            f"### n={metric['n']} 模块聚合 Top",
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


def _summary_row(name: str, stat: dict[str, Any]) -> str:
    """生成统计表单行。"""
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
# 外部服务与测试数据
# ─────────────────────────────────────────────────────────────────────

def _check_docker() -> bool:
    """检查必要 Docker 容器是否运行。"""
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
    """等待 PostgreSQL、Redis、Kafka 可用。"""
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
    """启动 OPC UA 仿真服务。"""
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
    """停止 OPC UA 仿真服务。"""
    for runtime in runtimes:
        try:
            runtime.stop()
        except Exception:
            pass


def _enable_n_acq_tasks(n: int, acquisition_mode: str) -> None:
    """启用前 n 个采集任务。"""
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
    """设置测试所需环境变量。"""
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


# ─────────────────────────────────────────────────────────────────────
# 采集链路构造与单轮执行
# ─────────────────────────────────────────────────────────────────────

def _build_pipeline() -> tuple[Any, Any, Any, Any, Any]:
    """构造采集链路依赖对象。"""
    state_cache = RedisSourceStateCache(
        settings=RedisSourceStateCacheSettings(
            host="127.0.0.1",
            port=16379,
            db=0,
            hash_key=HASH_KEY,
            station_id=STATION_ID,
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

    registry = StaticSourceAcquisitionPortRegistry(
        {
            "opcua": OpcUaSourceAcquisitionAdapter(),
            "OPC_UA": OpcUaSourceAcquisitionAdapter(),
        }
    )

    return config_repo, definition_repo, registry, state_cache, emit_usecase


def _run_one_level(
    *,
    mode: str,
    configs: list[Any],
    definition_repo: Any,
    registry: Any,
    state_cache: Any,
    emit_usecase: Any,
) -> dict[str, Any]:
    """执行一个压力层级。"""
    print(f"\n── {mode} {len(configs)} config(s), {LEVEL_DURATION_S}s ──")

    if mode == "polling":
        return _run_polling_level(
            configs=configs,
            definition_repo=definition_repo,
            registry=registry,
            state_cache=state_cache,
            emit_usecase=emit_usecase,
        )

    return _run_subscribe_level(
        configs=configs,
        definition_repo=definition_repo,
        registry=registry,
        state_cache=state_cache,
        emit_usecase=emit_usecase,
    )


def _run_polling_level(
    *,
    configs: list[Any],
    definition_repo: Any,
    registry: Any,
    state_cache: Any,
    emit_usecase: Any,
) -> dict[str, Any]:
    """执行 polling 模式压力层级。"""
    pull_usecase = PullSourceStateUseCase(
        acquisition_definition_port=definition_repo,
        acquisition_port_registry=registry,
        state_cache_port=state_cache,
        snapshot_emitter=emit_usecase,
    )

    loop_count = 0
    execute_cost_ms: list[float] = []
    deadline = time.time() + LEVEL_DURATION_S

    while time.time() < deadline:
        started_at = time.time()
        asyncio.run(pull_usecase.execute(configs))
        execute_cost_ms.append((time.time() - started_at) * 1000)
        loop_count += 1
        time.sleep(0.9)

    return {
        "mode": "polling",
        "loops": loop_count,
        "execute_ms": _summary(execute_cost_ms),
    }


def _run_subscribe_level(
    *,
    configs: list[Any],
    definition_repo: Any,
    registry: Any,
    state_cache: Any,
    emit_usecase: Any,
) -> dict[str, Any]:
    """执行 subscribe 模式压力层级。"""
    subscribe_usecase = SubscribeSourceStateUseCase(
        acquisition_definition_port=definition_repo,
        acquisition_port_registry=registry,
        state_cache_port=state_cache,
        snapshot_emitter=emit_usecase,
    )

    stop_event = threading.Event()
    errors: list[str] = []

    def run_subscriber() -> None:
        try:
            asyncio.run(subscribe_usecase.execute(configs, stop_event))
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


def _build_ramp(max_n: int) -> list[int]:
    """生成压力层级。"""
    ramp_env = os.environ.get("LOAD_RAMP", "").strip()

    if ramp_env:
        values = []
        for item in ramp_env.split(","):
            item = item.strip()
            if item.isdigit():
                value = int(item)
                if 1 <= value <= max_n:
                    values.append(value)
        return sorted(set(values))

    return sorted({value for value in (1, 5, 10, 15, 20, 25, max_n) if value <= max_n})


# ─────────────────────────────────────────────────────────────────────
# Pytest 入口
# ─────────────────────────────────────────────────────────────────────

@pytest.mark.load
def test_pipeline_load() -> None:
    """执行完整负载测试，并只输出一个 Markdown 报告。"""
    mode = os.environ.get("LOAD_MODE", "polling")
    if mode not in {"polling", "subscribe"}:
        raise ValueError(f"LOAD_MODE 只能是 polling 或 subscribe，当前为 {mode}")

    if not _check_docker():
        pytest.skip("Docker 服务未运行")

    _setup_env()
    _wait_services()

    init_db(force=True)
    generate_all_sample_data()

    fleet = OpcUaFleetRuntime.from_database()
    runtimes = fleet._runtimes
    level_metrics: list[dict[str, Any]] = []

    try:
        started_count = _start_servers(runtimes)
        if started_count == 0:
            pytest.fail("没有任何 OPC UA 仿真服务成功启动，请检查端口是否被占用")

        time.sleep(WARMUP_S)

        config_repo, definition_repo, registry, state_cache, emit_usecase = _build_pipeline()

        acquisition_mode = "READ_ONCE" if mode == "polling" else "SUBSCRIBE"
        _enable_n_acq_tasks(len(runtimes), acquisition_mode)
        all_configs = config_repo.list_enabled()

        ramp = _build_ramp(min(len(runtimes), len(all_configs)))
        if not ramp:
            pytest.fail("没有可用压力层级，请检查样例数据或 LOAD_RAMP")

        redis_client = redis_module.Redis(host="127.0.0.1", port=16379, db=0)

        for n in ramp:
            try:
                redis_client.delete(HASH_KEY)
            except Exception:
                pass

            group_id = f"load-{mode}-{n:02d}-{uuid.uuid4().hex[:8]}"
            capture = KafkaCapture(TOPIC, KAFKA_BS, group_id)
            capture.start()

            profile = cProfile.Profile()
            started_at = time.time()

            profile.enable()
            try:
                runner = _run_one_level(
                    mode=mode,
                    configs=all_configs[:n],
                    definition_repo=definition_repo,
                    registry=registry,
                    state_cache=state_cache,
                    emit_usecase=emit_usecase,
                )
            finally:
                profile.disable()
                capture_result = capture.stop(KAFKA_DRAIN_S)

            duration_s = time.time() - started_at
            profile_data = _profile_summary(profile, PROFILE_TOP_N)

            metric = _analyze_records(
                records=capture_result["records"],
                mode=mode,
                n=n,
                duration_s=duration_s,
                runner=runner,
                profile=profile_data,
                capture_meta=capture_result,
            )
            level_metrics.append(metric)

            print(
                "  "
                f"n={n}: "
                f"messages={metric['messages']} "
                f"states={metric['states']} "
                f"states/s={_fmt_rate(metric['throughput']['states_per_s'])} "
                f"lat_p95={_fmt_ms(metric['latency_ms'].get('p95'))} "
                f"period_p95={_fmt_ms(metric['period_ms'].get('p95'))} "
                f"gaps={metric['gaps']['count']}"
            )

        _write_report(mode, ramp, level_metrics)

    finally:
        _stop_servers(runtimes)
        if fleet._temp_dir:
            fleet._temp_dir.cleanup()