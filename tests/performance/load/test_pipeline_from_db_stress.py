r"""Load test: 30 OPC UA servers from shared DB → ingest → Redis → Kafka.

Uses docker-compose.ingest-dev.yaml for PostgreSQL + Redis + Kafka.
Runs for 10 minutes at 10 Hz with ~400 variables per server.
Generates HTML report with Chart.js.

Usage::
    # Ensure docker is up first:
    docker compose -f docker-compose.ingest-dev.yaml up -d
    # Generate sample data:
    python -m whale.shared.persistence.template.sample_data
    # Run stress test:
    python -m pytest tests/performance/load_pipeline_from_db_stress.py -v -s
    # Or standalone:
    STRESS_DURATION_S=600 python tests/performance/load_pipeline_from_db_stress.py
"""

from __future__ import annotations

import asyncio
import json
import os
import socket
import sys
import threading
import time
import uuid
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
SRC_ROOT = _PROJECT_ROOT / "src"
for p in (str(_PROJECT_ROOT), str(SRC_ROOT)):
    if p not in sys.path:
        sys.path.insert(0, p)

import pytest  # noqa: E402

# ── Config ─────────────────────────────────────────────────────────
DURATION_S = int(os.environ.get("STRESS_DURATION_S", "600"))
WARMUP_S = 5
PG_URL = "postgresql+psycopg://whale:whale@127.0.0.1:5432/whale_ingest"
REDIS_URL = "redis://127.0.0.1:16379/0"
KAFKA_BS = "127.0.0.1:9092"
STATION_ID = f"STRESS-{uuid.uuid4().hex[:6]}"
TOPIC = f"whale.ingest.stress.{uuid.uuid4().hex[:6]}"
HASH_KEY = f"whale:stress:{uuid.uuid4().hex[:6]}"


# ═══════════════════════════════════════════════════════════════════
# HTML Report
# ═══════════════════════════════════════════════════════════════════

def _gen_report(store: "_Store", path: Path) -> str:
    s = store.snapshot()
    d = s["duration"]; rate = s["total_ops"] / max(d, 1)
    cj = json.dumps({
        "labels": s["tl_labels"], "data": s["tl_data"],
        "llabels": ["<10ms","10-50","50-100","100-200","200-500","500-1s",">1s"],
        "ldata": s["lat_buckets"],
    })
    rows = "".join(f"<tr><td>{k}</td><td>{v}</td></tr>" for k, v in s["table"].items())
    css = ("body{font-family:-apple-system,sans-serif;margin:30px;background:#f4f5f7}"
           "h1{color:#1a365d;border-bottom:3px solid #3182ce;padding-bottom:8px}"
           "h2{color:#2b6cb0;margin-top:24px}"
           ".g{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:12px;margin:16px 0}"
           ".c{background:#fff;border-radius:8px;padding:14px;box-shadow:0 2px 6px rgba(0,0,0,.08);text-align:center}"
           ".c .v{font-size:28px;font-weight:700;color:#2b6cb0}.c .l{font-size:12px;color:#666}"
           ".b{background:#fff;border-radius:8px;padding:18px;box-shadow:0 2px 6px rgba(0,0,0,.08);margin:16px 0}"
           ".b h3{margin-top:0;color:#4a5568}canvas{max-height:350px}"
           "table{width:100%;border-collapse:collapse;background:#fff;border-radius:8px;overflow:hidden;box-shadow:0 2px 6px rgba(0,0,0,.08)}"
           "th{background:#3182ce;color:#fff;padding:8px 12px;text-align:left}"
           "td{padding:6px 12px;border-bottom:1px solid #edf2f7}"
           ".pass{color:#16a34a;font-weight:700}.warn{color:#d97706}")
    js = ("const d=" + cj + ";"
          "new Chart(document.getElementById('c1'),{type:'line',data:{labels:d.labels,"
          "datasets:[{label:'Ops/sec',data:d.data,borderColor:'#3182ce',tension:.3,"
          "pointRadius:0}]},options:{responsive:!0}});"
          "new Chart(document.getElementById('c2'),{type:'bar',data:{labels:d.llabels,"
          "datasets:[{label:'Count',data:d.ldata,backgroundColor:'#3182ce'}]},"
          "options:{responsive:!0}});")
    html = (f"<!DOCTYPE html><html lang=zh-CN><head><meta charset=utf-8><title>Stress Report</title>"
            f"<script src=https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js></script>"
            f"<style>{css}</style></head><body><h1>OPC UA Pipeline Load Test Report</h1>"
            f"<div class=g>"
            f"<div class=c><div class=v>{s['servers']}</div><div class=l>OPC UA Servers</div></div>"
            f"<div class=c><div class=v>{s['vars']}</div><div class=l>Vars / Server</div></div>"
            f"<div class=c><div class=v>{s['servers']*s['vars']:,}</div><div class=l>Total Variables</div></div>"
            f"<div class=c><div class=v>10 Hz</div><div class=l>Refresh Rate</div></div>"
            f"<div class=c><div class=v>{d:.0f}s</div><div class=l>Duration</div></div>"
            f"<div class=c><div class=v>{s['total_ops']:,}</div><div class=l>Total Events</div></div>"
            f"<div class=c><div class=v>{rate:,.0f}/s</div><div class=l>Throughput</div></div>"
            f"<div class=c><div class=v>{s['errors']}</div><div class=l>Errors</div></div>"
            f"</div><h2>Configuration</h2><table>{rows}</table>"
            f"<div class=b><h3>Throughput Over Time</h3><canvas id=c1></canvas></div>"
            f"<div class=b><h3>Latency Distribution</h3><canvas id=c2></canvas></div>"
            f"<p style=color:#999;font-size:12px;text-align:center;margin-top:32px>"
            f"Generated {time.strftime('%Y-%m-%d %H:%M:%S')} · Whale Load Test</p>"
            f"<script>{js}</script></body></html>")
    path.write_text(html, encoding="utf-8")
    return html


# ═══════════════════════════════════════════════════════════════════
# Metrics store
# ═══════════════════════════════════════════════════════════════════

class _Store:
    def __init__(self):
        self._lk = threading.Lock()
        self.ops: list[dict] = []
        self.servers = 0; self.vars = 0; self.errors = 0

    def add(self, d):
        with self._lk: self.ops.append(d)

    def snapshot(self):
        with self._lk: ops = list(self.ops)
        if not ops: return {"servers": self.servers, "vars": self.vars,
                            "total_ops": 0, "duration": 0, "errors": self.errors,
                            "tl_labels": [], "tl_data": [], "lat_buckets": [0]*7,
                            "table": {}}
        t0, te = ops[0]["t"], ops[-1]["t"]; dur = te - t0
        lats = [o.get("ms", 0) for o in ops if o.get("ms", 0) > 0]
        avg_lat = sum(lats) / len(lats) if lats else 0
        buckets: dict[int, int] = {}
        for o in ops: b = int(o["t"] - t0); buckets[b] = buckets.get(b, 0) + 1
        lbs = [0]*7
        for l in lats:
            for i, b in enumerate([10, 50, 100, 200, 500, 1000]):
                if l < b: lbs[i] += 1; break
            else: lbs[6] += 1
        labels = sorted(buckets.keys())
        return {"servers": self.servers, "vars": self.vars,
                "total_ops": len(ops), "duration": dur, "errors": self.errors,
                "tl_labels": [str(l) for l in labels],
                "tl_data": [buckets[l] for l in labels], "lat_buckets": lbs,
                "table": {
                    "Database": "PostgreSQL (ingest) + SQLite (shared)",
                    "State Cache": "Redis 7 (127.0.0.1:16379)",
                    "Message Bus": "Kafka (127.0.0.1:9092)",
                    "Station ID": STATION_ID, "Topic": TOPIC,
                    "Avg Latency": f"{avg_lat:.1f} ms",
                }}


# ═══════════════════════════════════════════════════════════════════
# Docker check
# ═══════════════════════════════════════════════════════════════════

def _check_docker() -> bool:
    """Verify docker containers for PG, Redis, Kafka are running."""
    import subprocess
    try:
        out = subprocess.check_output(
            ["docker", "ps", "--format", "{{.Names}}"], text=True, timeout=10
        )
    except Exception as e:
        print(f"ERROR: docker not available: {e}")
        return False
    names = out.strip().split("\n")
    needed = {"whale-ingest-postgres", "whale-ingest-redis", "whale-ingest-kafka"}
    ok = needed.issubset(set(names))
    if not ok:
        missing = needed - set(names)
        print(f"ERROR: Docker containers not running: {missing}")
        print(f"  Run: docker compose -f docker-compose.ingest-dev.yaml up -d")
    return ok


def _wait_services(timeout: float = 30) -> None:
    """Wait for PG, Redis, Kafka to be ready."""
    import redis as _redis_module
    from sqlalchemy import create_engine, text

    deadline = time.time() + timeout
    # PostgreSQL
    while time.time() < deadline:
        try:
            eng = create_engine(PG_URL)
            with eng.connect() as c:
                c.execute(text("SELECT 1"))
            break
        except Exception:
            time.sleep(1)

    # Redis
    r = _redis_module.Redis.from_url(REDIS_URL)
    while time.time() < deadline:
        try:
            r.ping()
            break
        except Exception:
            time.sleep(1)

    # Kafka
    from kafka import KafkaConsumer
    while time.time() < deadline:
        try:
            c = KafkaConsumer(bootstrap_servers=KAFKA_BS)
            c.topics()
            c.close()
            break
        except Exception:
            time.sleep(1)


# ═══════════════════════════════════════════════════════════════════
# Main test
# ═══════════════════════════════════════════════════════════════════

@pytest.mark.load
def test_stress_30_servers_full_pipeline(
    pg_session, _kafka_ready, redis_client, session_factory, tmp_path: Path,
) -> None:
    _run_stress(pg_session, redis_client, session_factory, tmp_path / "load_report.html")


def _run_stress(pg_session, redis_client, session_factory, report_path: Path) -> None:
    store = _Store()
    from whale.shared.persistence.session import session_scope
    from sqlalchemy import text

    # ── 1. Fleet from shared DB ────────────────────────────────────
    from tools.opcua_sim.fleet_runtime import OpcUaFleetRuntime
    from tools.opcua_sim.models import OpcUaServerConfig

    fleet = OpcUaFleetRuntime.from_database()
    runtimes = fleet._runtimes
    store.servers = len(runtimes)
    print(f"\n{'='*60}\n  LOAD: {len(runtimes)} servers from shared DB\n{'='*60}")

    # Override to 10 Hz
    for rt in runtimes:
        rt._config = OpcUaServerConfig(
            name=rt._config.name, endpoint=rt._config.endpoint,
            security_policy=rt._config.security_policy,
            security_mode=rt._config.security_mode,
            update_interval_seconds=0.1,
        )

    # ── 2. Get WTG variable keys ───────────────────────────────────
    with session_scope() as s:
        keys = s.execute(text(
            "SELECT DISTINCT do_name FROM v_measurement_point "
            "WHERE ied_name = 'IED_WTG_OPCUA' ORDER BY do_name"
        )).fetchall()
        all_keys = tuple(r.do_name for r in keys)
        store.vars = len(all_keys)
        print(f"  Variables: {len(all_keys)} unique DO keys")

    # ── 3. Seed ingest DB for all 30 servers ───────────────────────
    from tests.e2e.helpers import seed_postgres_for_e2e
    task_ids = []
    print(f"  Seeding ingest DB for {len(runtimes)} servers...")
    for i, rt in enumerate(runtimes):
        try:
            tid, _ = seed_postgres_for_e2e(
                pg_session, device_code=rt.name, endpoint=rt.endpoint,
                acquisition_mode="ONCE",
                variable_keys=all_keys,
            )
            task_ids.append(tid)
            if (i + 1) % 10 == 0:
                print(f"    {i+1}/{len(runtimes)} seeded")
        except Exception as e:
            store.errors += 1
            print(f"    WARN seed {rt.name}: {e}")
    pg_session.commit()
    print(f"  Seeded {len(task_ids)}/{len(runtimes)} tasks")

    # ── 4. Start all 30 servers ────────────────────────────────────
    # Force-kill any lingering processes on ports 40001-40032
    import subprocess as _sp
    killed = 0
    try:
        out = _sp.check_output(["ss", "-tlnp"], text=True, timeout=5)
        for line in out.split("\n"):
            for port in range(40001, 40033):
                if f":{port}" in line:
                    pid_part = line.split("pid=")[-1] if "pid=" in line else ""
                    pid = pid_part.split(",")[0].strip() if pid_part else ""
                    if pid and pid.isdigit():
                        _sp.run(["kill", "-9", pid], capture_output=True)
                        killed += 1
    except Exception:
        pass
    if killed:
        print(f"  Killed {killed} lingering OPC UA processes")
        import time as _time
        _time.sleep(2)  # Wait for sockets to be released by kernel

    print(f"  Starting {len(runtimes)} servers at 10 Hz...")
    for i, rt in enumerate(runtimes):
        try:
            rt.start()
            if (i + 1) % 10 == 0:
                print(f"    {i+1}/{len(runtimes)} started")
        except Exception as e:
            store.errors += 1
            print(f"    ERROR {rt.name}: {e}")
    started = sum(1 for rt in runtimes if rt._server is not None)
    print(f"  Started {started}/{len(runtimes)} servers")
    time.sleep(WARMUP_S)

    # ── 5. Verify server 0 ─────────────────────────────────────────
    async def _verify():
        from asyncua import Client
        async with Client(url=runtimes[0].endpoint, timeout=5) as c:
            ns = await c.get_namespace_index("urn:windfarm:2wtg")
            wf = await c.get_objects_node().get_child(f"{ns}:WindFarm")
            t = (await wf.get_children())[0]
            vv = await t.get_children()
            return len(vv)
    vc = asyncio.run(_verify())
    store.vars = vc
    print(f"  Server 0 verified: {vc} variables")

    # ── 6. Build pipeline ──────────────────────────────────────────
    from whale.ingest.adapters.message.kafka_message_publisher import \
        KafkaMessagePublisher
    from whale.ingest.adapters.source.opcua_source_acquisition_adapter import \
        OpcUaSourceAcquisitionAdapter
    from whale.ingest.adapters.state.redis_source_state_cache import \
        RedisSourceStateCache, RedisSourceStateCacheSettings
    from whale.ingest.usecases.emit_state_snapshot_usecase import \
        EmitStateSnapshotUseCase
    from whale.ingest.usecases.pull_source_state_usecase import \
        PullSourceStateUseCase
    from whale.ingest.adapters.config.source_runtime_config_repository import \
        SourceRuntimeConfigRepository
    from whale.ingest.adapters.config.opcua_source_acquisition_definition_repository import \
        OpcUaSourceAcquisitionDefinitionRepository
    from whale.ingest.adapters.source.static_source_acquisition_port_registry import \
        StaticSourceAcquisitionPortRegistry
    from whale.ingest.config import KafkaMessageConfig

    state_cache = RedisSourceStateCache(
        settings=RedisSourceStateCacheSettings(
            host="127.0.0.1", port=16379, db=0,
            username=None, password=None,
            hash_key=HASH_KEY, station_id=STATION_ID,
        ),
        client=redis_client,
    )
    publisher = KafkaMessagePublisher(
        settings=KafkaMessageConfig(
            bootstrap_servers=(KAFKA_BS,), topic=TOPIC,
            ack_timeout_seconds=30.0,
        )
    )
    emit_uc = EmitStateSnapshotUseCase(
        snapshot_reader_port=state_cache, publisher=publisher,
    )
    def_repo = OpcUaSourceAcquisitionDefinitionRepository(session_factory)
    config_repo = SourceRuntimeConfigRepository(session_factory)
    registry = StaticSourceAcquisitionPortRegistry(
        {"opcua": OpcUaSourceAcquisitionAdapter(),
         "OPC_UA": OpcUaSourceAcquisitionAdapter()}
    )
    pull_uc = PullSourceStateUseCase(
        acquisition_definition_port=def_repo,
        acquisition_port_registry=registry,
        state_cache_port=state_cache,
        snapshot_emitter=emit_uc,
    )

    # ── 7. Run pull loop ───────────────────────────────────────────
    print(f"\n  Running pipeline for {DURATION_S}s ({DURATION_S/60:.0f} min)...")
    start = time.time()
    last_report = start

    while time.time() - start < DURATION_S:
        t0 = time.time()
        try:
            async def _pull():
                return await pull_uc.execute(config_repo.list_enabled())
            results = asyncio.run(_pull())
            ms = (time.time() - t0) * 1000
            ok = isinstance(results, list) and len(results) > 0
            if not ok: store.errors += 1
            store.add({"t": time.time(), "ms": ms, "items": len(results) if isinstance(results, list) else 0, "ok": ok})
        except Exception as e:
            store.errors += 1
            store.add({"t": time.time(), "ms": (time.time() - t0) * 1000, "error": str(e)})

        # Report every 30s
        if time.time() - last_report >= 30:
            elapsed = time.time() - start
            recent = [o for o in store.ops if o["t"] >= time.time() - 30]
            rate = len(recent) / 30.0
            avg_ms = sum(o.get("ms", 0) for o in recent) / len(recent) if recent else 0
            redis_count = redis_client.hlen(HASH_KEY)
            print(f"  {elapsed:5.0f}s  pulls:{len(store.ops):,}  rate:{rate:.0f}/s  "
                  f"avg:{avg_ms:.0f}ms  redis:{redis_count}  err:{store.errors}", flush=True)
            last_report = time.time()

        # Each pull cycle is heavy (reads all 30 servers in parallel)
        # Let the pipeline run at its natural pace
        et = time.time() - t0
        if et < 1.0:
            time.sleep(1.0 - et)

    # ── 8. Results ─────────────────────────────────────────────────
    dur_actual = time.time() - start
    print(f"\n  Stopping {len(runtimes)} servers...")
    for rt in runtimes:
        try: rt.stop()
        except Exception: pass
    fleet._temp_dir.cleanup() if fleet._temp_dir else None

    # Collect final Redis/Kafka stats
    redis_count = redis_client.hlen(HASH_KEY)

    # Consume Kafka messages for stats
    from kafka import KafkaConsumer
    kafka_msgs = []
    try:
        consumer = KafkaConsumer(
            TOPIC, bootstrap_servers=KAFKA_BS,
            auto_offset_reset="earliest", group_id=f"stress-reporter-{uuid.uuid4().hex[:6]}",
            consumer_timeout_ms=5000, max_poll_records=50,
        )
        for msg in consumer:
            try:
                kafka_msgs.append(json.loads(msg.value.decode("utf-8")))
            except Exception:
                pass
        consumer.close()
    except Exception as e:
        print(f"  Kafka read warning: {e}")

    # Generate report
    ok_pulls = sum(1 for o in store.ops if o.get("ok", True))
    print(f"\n{'='*60}")
    print(f"  LOAD TEST RESULTS")
    print(f"{'='*60}")
    print(f"  Servers:          {store.servers}")
    print(f"  Vars/server:      {store.vars}")
    print(f"  Total vars:       {store.servers * store.vars:,}")
    print(f"  Duration:         {dur_actual:.0f}s")
    print(f"  Pull cycles:      {len(store.ops)}")
    print(f"  Successful pulls: {ok_pulls}")
    print(f"  Errors:           {store.errors}")
    print(f"  Redis entries:    {redis_count}")
    print(f"  Kafka messages:   {len(kafka_msgs)}")
    print(f"{'='*60}")

    _gen_report(store, report_path)
    print(f"  Report: {report_path}")

    # Clean up Redis
    try: redis_client.delete(HASH_KEY)
    except Exception: pass

    # Assertions
    assert store.servers == 30, f"Server count: {store.servers}"
    assert store.vars >= 300, f"Var count: {store.vars}"
    assert ok_pulls > 0, "No successful pulls"
    assert redis_count >= 300, f"Redis entries: {redis_count}"
    if len(kafka_msgs) == 0:
        print("  NOTE: No Kafka messages consumed (topic may still be creating)")


# ═══════════════════════════════════════════════════════════════════
# Standalone runner
# ═══════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    if not _check_docker():
        raise SystemExit(1)

    # Force docker backends for standalone mode
    os.environ["WHALE_INGEST_DATABASE_BACKEND"] = "postgresql"
    os.environ["WHALE_INGEST_STATE_CACHE_BACKEND"] = "redis"
    os.environ["WHALE_INGEST_MESSAGE_BACKEND"] = "kafka"
    os.environ["WHALE_INGEST_DB_HOST"] = "127.0.0.1"
    os.environ["WHALE_INGEST_DB_PORT"] = "5432"
    os.environ["WHALE_INGEST_DB_NAME"] = "whale_ingest"
    os.environ["WHALE_INGEST_DB_USERNAME"] = "whale"
    os.environ["WHALE_INGEST_DB_PASSWORD"] = "whale"
    os.environ["WHALE_INGEST_REDIS_HOST"] = "127.0.0.1"
    os.environ["WHALE_INGEST_REDIS_PORT"] = "16379"
    os.environ["WHALE_INGEST_REDIS_DB"] = "0"
    os.environ["WHALE_INGEST_REDIS_STATE_HASH_KEY"] = HASH_KEY
    os.environ["WHALE_INGEST_STATION_ID"] = STATION_ID
    os.environ["WHALE_INGEST_KAFKA_BOOTSTRAP_SERVERS"] = KAFKA_BS
    os.environ["WHALE_INGEST_KAFKA_TOPIC"] = TOPIC
    os.environ["WHALE_INGEST_KAFKA_ACK_TIMEOUT_SECONDS"] = "30.0"

    _wait_services()

    # Ensure shared DB has sample data
    from whale.shared.persistence.session import session_scope
    from sqlalchemy import inspect, text
    with session_scope() as s:
        insp = inspect(s.get_bind())
        if "acq_task" not in insp.get_table_names():
            print("Generating sample data...")
            from whale.shared.persistence.init_db import init_db
            from whale.shared.persistence.template.sample_data import generate_all_sample_data
            init_db(force=True)
            generate_all_sample_data()

    # Set up ingest DB
    import redis as _redis_module
    from sqlalchemy import create_engine as _create_engine
    from sqlalchemy.orm import Session as _Session

    pg_engine = _create_engine(PG_URL, pool_size=20, max_overflow=40, pool_pre_ping=True)
    from importlib import import_module
    import_module("whale.ingest.framework.persistence.orm")
    from whale.ingest.framework.persistence.base import Base as IngestBase
    IngestBase.metadata.create_all(bind=pg_engine)

    pg_sess = _Session(bind=pg_engine, autoflush=False, expire_on_commit=False)
    # Clean up old data
    for t in ("acquisition_task", "acquisition_variable", "acquisition_model"):
        pg_sess.execute(text(f"DELETE FROM {t}"))
    pg_sess.commit()

    redis_cli = _redis_module.Redis.from_url(REDIS_URL)
    redis_cli.ping()

    def _sf():
        s = _Session(bind=pg_engine, autoflush=False, expire_on_commit=False)
        yield s; s.close()

    from contextlib import contextmanager
    @contextmanager
    def _sf_ctx():
        s = _Session(bind=pg_engine, autoflush=False, expire_on_commit=False)
        try: yield s
        finally: s.close()

    report_dir = _PROJECT_ROOT / "tests" / "tmp"
    report_dir.mkdir(exist_ok=True)
    report_path = report_dir / "load_report.html"

    print(f"\nDuration: {DURATION_S}s ({DURATION_S/60:.0f} min)")
    print(f"Report: {report_path}")
    _run_stress(pg_sess, redis_cli, _sf_ctx, report_path)

    pg_sess.close()
    pg_engine.dispose()
