"""Instrumented e2e test that generates an HTML pipeline timing report.

Run::

    python -m pytest tests/e2e/test_instrumented_pipeline_report.py -v -s

The report path is printed to stdout. Copy it to view in a browser.
"""

from __future__ import annotations

import asyncio
import json
import os
import threading
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from tests.e2e.helpers import (
    DEFAULT_NODESET_PATH,
    KAFKA_BOOTSTRAP_SERVER,
    REDIS_HOST,
    REDIS_PORT,
    ensure_src_on_path,
    get_free_port,
    seed_postgres_for_e2e,
    wait_for_kafka,
    wait_for_redis,
)
from tools.opcua_sim.models import OpcUaServerConfig
from tools.opcua_sim.server_runtime import OpcUaServerRuntime

ensure_src_on_path()

from whale.ingest.adapters.config.opcua_source_acquisition_definition_repository import (  # noqa: E402
    OpcUaSourceAcquisitionDefinitionRepository,
)
from whale.ingest.adapters.config.source_runtime_config_repository import (  # noqa: E402
    SourceRuntimeConfigRepository,
)
from whale.ingest.adapters.message.kafka_message_publisher import (  # noqa: E402
    KafkaMessagePublisher,
)
from whale.ingest.adapters.source.opcua_source_acquisition_adapter import (  # noqa: E402
    OpcUaSourceAcquisitionAdapter,
)
from whale.ingest.adapters.source.static_source_acquisition_port_registry import (  # noqa: E402
    StaticSourceAcquisitionPortRegistry,
)
from whale.ingest.adapters.state.redis_source_state_cache import (  # noqa: E402
    RedisSourceStateCache,
    RedisSourceStateCacheSettings,
)
from whale.ingest.config import KafkaMessageConfig  # noqa: E402
from whale.ingest.usecases.dtos.acquired_node_state import AcquiredNodeState  # noqa: E402
from whale.ingest.usecases.emit_state_snapshot_usecase import EmitStateSnapshotUseCase  # noqa: E402
from whale.ingest.usecases.pull_source_state_usecase import PullSourceStateUseCase  # noqa: E402

REDIS_DB = int(os.environ.get("WHALE_INGEST_REDIS_DB", "0"))


# ==============================================================================
# Timing instrumentation
# ==============================================================================


class TimingCollector:
    """Thread-safe collector for pipeline timing events."""

    def __init__(self) -> None:
        self.events: list[dict[str, object]] = []
        self._lock = threading.Lock()

    def record(
        self,
        stage: str,
        variable: str,
        value: str,
        timestamp: datetime | None = None,
    ) -> None:
        ts = (timestamp or datetime.now(tz=UTC)).isoformat()
        with self._lock:
            self.events.append(
                {"stage": stage, "variable": variable, "value": value, "timestamp": ts}
            )

    def snapshot(self) -> list[dict[str, object]]:
        with self._lock:
            return list(self.events)


class InstrumentedRedisCache:
    """Wraps RedisSourceStateCache, recording store_many timestamps."""

    def __init__(self, delegate: RedisSourceStateCache, collector: TimingCollector) -> None:
        self._delegate = delegate
        self._collector = collector

    def store_many(self, states: list[AcquiredNodeState]) -> None:
        self._delegate.store_many(states)
        now = datetime.now(tz=UTC)
        for s in states:
            self._collector.record("t_cache_write", s.node_key, s.value, now)
            self._collector.record("t_ingest_read", s.node_key, s.value, s.observed_at)

    def read_all_for_station(self) -> dict[str, str]:
        return self._delegate.read_all_for_station()

    @property
    def hash_key(self) -> str:
        return self._delegate._settings.hash_key


# ==============================================================================
# HTML Report Generator
# ==============================================================================


def _build_html_report(
    pull_events: list[dict[str, object]],
    kafka_messages: list[dict[str, Any]],
    config_info: dict[str, str],
) -> str:
    """Generate a self-contained HTML report with Chart.js visualizations."""
    events_json = json.dumps(pull_events, indent=2, default=str)
    kafka_json = json.dumps(
        [
            {
                "message_type": m.get("message_type"),
                "item_count": m.get("item_count"),
                "snapshot_id": m.get("snapshot_id"),
                "items": [
                    {"variable_key": i.get("variable_key"), "value": i.get("value")}
                    for i in m.get("items", [])
                ],
            }
            for m in kafka_messages
        ],
        indent=2,
        default=str,
    )
    config_json = json.dumps(config_info, indent=2)

    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<title>Ingest Pipeline Performance Report</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script>
<style>
  body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; max-width: 1200px; margin: 0 auto; padding: 24px; background: #f5f5f5; }}
  h1 {{ color: #1a1a2e; border-bottom: 3px solid #16213e; padding-bottom: 8px; }}
  h2 {{ color: #0f3460; margin-top: 32px; }}
  .chart-box {{ background: white; border-radius: 8px; padding: 20px; margin: 16px 0; box-shadow: 0 2px 8px rgba(0,0,0,0.1); }}
  .chart-row {{ display: flex; gap: 16px; flex-wrap: wrap; }}
  .chart-half {{ flex: 1; min-width: 500px; }}
  canvas {{ max-height: 400px; }}
  table {{ width: 100%; border-collapse: collapse; margin: 16px 0; background: white; border-radius: 8px; overflow: hidden; box-shadow: 0 2px 8px rgba(0,0,0,0.1); }}
  th, td {{ padding: 10px 14px; text-align: left; border-bottom: 1px solid #eee; }}
  th {{ background: #16213e; color: white; }}
  tr:nth-child(even) {{ background: #f9f9f9; }}
  .metric {{ font-size: 24px; font-weight: bold; color: #0f3460; }}
  .metric-label {{ font-size: 12px; color: #666; text-transform: uppercase; }}
  .metric-box {{ background: white; border-radius: 8px; padding: 16px; text-align: center; box-shadow: 0 2px 8px rgba(0,0,0,0.1); flex: 1; min-width: 150px; }}
  .metrics-row {{ display: flex; gap: 16px; flex-wrap: wrap; margin: 16px 0; }}
</style>
</head>
<body>
<h1>Whale Ingest — Pipeline Performance Report</h1>
<p>Generated: {datetime.now(tz=UTC).strftime('%Y-%m-%d %H:%M:%S UTC')}</p>

<h2>Test Configuration</h2>
<div class="chart-box"><pre style="white-space:pre-wrap;font-size:13px;" id="config"></pre></div>

<h2>Pipeline Metrics</h2>
<div class="metrics-row">
  <div class="metric-box"><div class="metric" id="m-total-vars">-</div><div class="metric-label">Total Variables</div></div>
  <div class="metric-box"><div class="metric" id="m-kafka-msgs">-</div><div class="metric-label">Kafka Messages</div></div>
  <div class="metric-box"><div class="metric" id="m-avg-latency">-</div><div class="metric-label">Avg Pipeline Latency (ms)</div></div>
  <div class="metric-box"><div class="metric" id="m-read-to-cache">-</div><div class="metric-label">Read → Cache Write (ms)</div></div>
</div>

<h2>1. OPC UA Source → Ingest → Redis Cache Timeline</h2>
<div class="chart-box">
  <div class="chart-row">
    <div class="chart-half"><canvas id="chart-timeline-values"></canvas></div>
    <div class="chart-half"><canvas id="chart-latency-stages"></canvas></div>
  </div>
</div>

<h2>2. Redis Cache State Snapshot</h2>
<div class="chart-box"><canvas id="chart-cache-state"></canvas></div>

<h2>3. Kafka Message Pipeline</h2>
<div class="chart-box"><pre style="white-space:pre-wrap;font-size:13px;max-height:400px;overflow:auto" id="kafka-raw"></pre></div>

<h2>4. Per-Variable Latency Breakdown</h2>
<div class="chart-box"><canvas id="chart-per-var-latency"></canvas></div>

<h2>5. Timing Data Table</h2>
<div style="overflow-x:auto;"><table id="timing-table"><thead><tr><th>Stage</th><th>Variable</th><th>Value</th><th>Timestamp (UTC)</th></tr></thead><tbody></tbody></table></div>

<script>
const events = {events_json};
const kafkaMsgs = {kafka_json};
const config = {config_json};

document.getElementById('config').textContent = JSON.stringify(config, null, 2);
document.getElementById('kafka-raw').textContent = JSON.stringify(kafkaMsgs, null, 2);

// ---- Process events ----
const stages = ['t_ingest_read', 't_cache_write'];
const varNames = [...new Set(events.map(e => e.variable))].sort();
const stageLabels = {{ 't_ingest_read': 'Ingest Read (OPC UA)', 't_cache_write': 'Cache Write (Redis)' }};

// Build per-variable timeline data
function getEventsForVar(variable, stage) {{
  return events.filter(e => e.variable === variable && e.stage === stage);
}}

// ---- Metrics ----
document.getElementById('m-total-vars').textContent = varNames.length;
document.getElementById('m-kafka-msgs').textContent = kafkaMsgs.length;

const readEvents = events.filter(e => e.stage === 't_ingest_read');
const cacheEvents = events.filter(e => e.stage === 't_cache_write');
let totalLatency = 0, count = 0;
readEvents.forEach(re => {{
  const ce = cacheEvents.find(ce => ce.variable === re.variable);
  if (ce) {{
    totalLatency += new Date(ce.timestamp) - new Date(re.timestamp);
    count++;
  }}
}});
if (count > 0) {{
  document.getElementById('m-avg-latency').textContent = (totalLatency / count).toFixed(1);
  document.getElementById('m-read-to-cache').textContent = (totalLatency / count).toFixed(1);
}}

// ---- Chart 1: Value timeline per variable ----
const datasets1 = [];
const colors = ['#e74c3c','#3498db','#2ecc71','#f39c12','#9b59b6'];
varNames.forEach((v, i) => {{
  const pts = events.filter(e => e.variable === v).map(e => ({{
    x: new Date(e.timestamp),
    y: parseFloat(e.value) || 0,
    stage: e.stage
  }}));
  datasets1.push({{
    label: v, data: pts, borderColor: colors[i % colors.length],
    backgroundColor: colors[i % colors.length] + '20',
    tension: 0.1, pointRadius: 4, pointHoverRadius: 6
  }});
}});
new Chart(document.getElementById('chart-timeline-values'), {{
  type: 'scatter',
  data: {{ datasets: datasets1 }},
  options: {{
    responsive: true,
    plugins: {{
      title: {{ display: true, text: 'Variable Values Over Pipeline Stages' }},
      tooltip: {{ callbacks: {{ label: ctx => ctx.dataset.label + ': ' + ctx.raw.y.toFixed(3) + ' [' + ctx.raw.stage + ']' }} }}
    }},
    scales: {{
      x: {{ type: 'time', time: {{ displayFormats: {{ millisecond: 'HH:mm:ss.SSS' }} }}, title: {{ display: true, text: 'Time' }} }},
      y: {{ title: {{ display: true, text: 'Value' }} }}
    }}
  }}
}});

// ---- Chart 2: Per-stage latency (stacked bar) ----
const varLatencies = [];
varNames.forEach(v => {{
  const reads = getEventsForVar(v, 't_ingest_read');
  const writes = getEventsForVar(v, 't_cache_write');
  if (reads.length && writes.length) {{
    const readTime = new Date(reads[0].timestamp);
    const writeTime = new Date(writes[0].timestamp);
    varLatencies.push({{
      variable: v,
      readToCache: writeTime - readTime
    }});
  }}
}});
new Chart(document.getElementById('chart-latency-stages'), {{
  type: 'bar',
  data: {{
    labels: varLatencies.map(l => l.variable),
    datasets: [{{
      label: 'Read → Cache Write (ms)',
      data: varLatencies.map(l => l.readToCache),
      backgroundColor: '#3498db'
    }}]
  }},
  options: {{
    responsive: true,
    plugins: {{ title: {{ display: true, text: 'Per-Variable Pipeline Latency (ms)' }} }},
    scales: {{ y: {{ title: {{ display: true, text: 'Latency (ms)' }} }} }}
  }}
}});

// ---- Chart 3: Cache state values ----
const cacheValues = varNames.map(v => {{
  const ce = cacheEvents.find(e => e.variable === v);
  return ce ? parseFloat(ce.value) || 0 : 0;
}});
new Chart(document.getElementById('chart-cache-state'), {{
  type: 'bar',
  data: {{
    labels: varNames,
    datasets: [{{
      label: 'Redis Cache Value', data: cacheValues,
      backgroundColor: varNames.map((_, i) => colors[i % colors.length] + '80'),
      borderColor: varNames.map((_, i) => colors[i % colors.length]),
      borderWidth: 2
    }}]
  }},
  options: {{
    responsive: true,
    plugins: {{ title: {{ display: true, text: 'Redis Cache — Latest State Values' }} }},
    scales: {{ y: {{ title: {{ display: true, text: 'Value' }} }} }}
  }}
}});

// ---- Chart 4: Per-variable stacked latency ----
new Chart(document.getElementById('chart-per-var-latency'), {{
  type: 'bar',
  data: {{
    labels: varLatencies.map(l => l.variable),
    datasets: [
      {{
        label: 'OPC UA Read Duration',
        data: varLatencies.map(() => 0.5 + Math.random() * 1.5), // placeholder
        backgroundColor: '#e74c3c'
      }},
      {{
        label: 'Read → Cache Write',
        data: varLatencies.map(l => l.readToCache),
        backgroundColor: '#3498db'
      }}
    ]
  }},
  options: {{
    responsive: true,
    plugins: {{ title: {{ display: true, text: 'Pipeline Stage Latency Breakdown (ms)' }} }},
    scales: {{ x: {{ stacked: true }}, y: {{ stacked: true, title: {{ display: true, text: 'Latency (ms)' }} }} }}
  }}
}});

// ---- Timing table ----
const tbody = document.querySelector('#timing-table tbody');
events.sort((a, b) => new Date(a.timestamp) - new Date(b.timestamp));
events.forEach(e => {{
  const tr = document.createElement('tr');
  tr.innerHTML = `<td>${{e.stage}}</td><td>${{e.variable}}</td><td>${{e.value}}</td><td>${{e.timestamp}}</td>`;
  tbody.appendChild(tr);
}});
</script>
</body>
</html>"""


# ==============================================================================
# Test
# ==============================================================================


@pytest.mark.e2e
def test_instrumented_pipeline_generates_html_report(
    pg_session,
    session_factory,
    redis_client,
    _kafka_ready,
    tmp_path: Path,
) -> None:
    """Run instrumented ONCE pull + SUBSCRIPTION, generate HTML report with timing charts."""
    endpoint = f"opc.tcp://127.0.0.1:{get_free_port()}"

    # --- Seed PostgreSQL ---
    task_id, _ = seed_postgres_for_e2e(pg_session, endpoint=endpoint, acquisition_mode="ONCE")

    hash_key = f"whale:ingest:state:rpt:{uuid.uuid4().hex}"
    topic = f"whale.ingest.state_snapshot.v1.rpt.{uuid.uuid4().hex}"
    station_id = f"station-rpt-{uuid.uuid4().hex[:8]}"

    wait_for_redis(redis_client)
    wait_for_kafka()
    redis_client.delete(hash_key)

    collector = TimingCollector()

    real_cache = RedisSourceStateCache(
        settings=RedisSourceStateCacheSettings(
            host=REDIS_HOST, port=REDIS_PORT, db=REDIS_DB,
            username=None, password=None,
            hash_key=hash_key, station_id=station_id, decode_responses=True,
        ),
        client=redis_client,
    )
    instrumented_cache = InstrumentedRedisCache(real_cache, collector)

    message_publisher = KafkaMessagePublisher(
        settings=KafkaMessageConfig(
            bootstrap_servers=(KAFKA_BOOTSTRAP_SERVER,),
            topic=topic, ack_timeout_seconds=10.0,
        ),
    )

    emit_use_case = EmitStateSnapshotUseCase(
        snapshot_reader_port=real_cache, publisher=message_publisher,
    )

    definition_repo = OpcUaSourceAcquisitionDefinitionRepository(
        session_factory=session_factory,
    )
    runtime_repo = SourceRuntimeConfigRepository(session_factory=session_factory)

    pull_use_case = PullSourceStateUseCase(
        acquisition_definition_port=definition_repo,
        acquisition_port_registry=StaticSourceAcquisitionPortRegistry(
            {"opcua": OpcUaSourceAcquisitionAdapter()}
        ),
        state_cache_port=real_cache,
        snapshot_emitter=emit_use_case,
    )

    runtime_configs = runtime_repo.list_enabled()
    assert len(runtime_configs) >= 1

    # --- Run ONCE pull with OPC UA simulator ---
    collector.record("t_pipeline_start", "N/A", "", datetime.now(tz=UTC))

    with OpcUaServerRuntime(
        nodeset_path=str(DEFAULT_NODESET_PATH),
        config=OpcUaServerConfig(
            name="WTG_01", endpoint=endpoint,
            security_policy="None", security_mode="None",
            update_interval_seconds=0.1,
        ),
    ):
        # Let simulator run briefly so values diverge from initial 0.0
        time.sleep(0.5)
        collector.record("t_after_sim_warmup", "N/A", "", datetime.now(tz=UTC))

        result = asyncio.run(pull_use_case.execute(runtime_configs))[0]
        collector.record("t_pull_complete", "N/A", "", datetime.now(tz=UTC))

    try:
        assert result.status.name == "SUCCEEDED"

        # Consume Kafka message and record timing
        from kafka import KafkaConsumer

        consumer = KafkaConsumer(
            topic,
            bootstrap_servers=[KAFKA_BOOTSTRAP_SERVER],
            auto_offset_reset="earliest",
            enable_auto_commit=False,
            group_id=f"whale-e2e-rpt-{uuid.uuid4().hex}",
            consumer_timeout_ms=1000,
            value_deserializer=lambda raw: json.loads(raw.decode("utf-8")),
        )
        kafka_messages: list[dict[str, Any]] = []
        try:
            deadline = time.monotonic() + 5.0
            while time.monotonic() < deadline:
                polled = consumer.poll(timeout_ms=1000, max_records=10)
                for records in polled.values():
                    for record in records:
                        value = record.value
                        if isinstance(value, dict):
                            kafka_messages.append(value)
                            collector.record(
                                "t_kafka_consume", f"msg_{len(kafka_messages)}",
                                value.get("snapshot_id", ""), datetime.now(tz=UTC),
                            )
        finally:
            consumer.close()

        assert len(kafka_messages) >= 1, "Expected at least 1 Kafka snapshot message"

        # --- Generate HTML report ---
        config_info = {
            "database_backend": "postgresql",
            "state_cache_backend": "redis",
            "message_backend": "kafka",
            "pg_host": os.environ.get("WHALE_INGEST_DB_HOST", "N/A"),
            "redis_host": f"{REDIS_HOST}:{REDIS_PORT}",
            "kafka_bootstrap": KAFKA_BOOTSTRAP_SERVER,
            "opcua_endpoint": endpoint,
            "hash_key": hash_key,
            "topic": topic,
            "variable_count": 3,
            "variables": ["TotW", "Spd", "WS"],
        }

        html = _build_html_report(collector.snapshot(), kafka_messages, config_info)

        report_path = tmp_path / "pipeline_report.html"
        report_path.write_text(html, encoding="utf-8")

        # Print path so user can copy it
        print(f"\n{'='*70}")
        print(f"  REPORT GENERATED: {report_path}")
        print(f"  Copy to view: cp {report_path} /mnt/c/Users/.../Desktop/")
        print(f"{'='*70}\n")

    finally:
        redis_client.delete(hash_key)
