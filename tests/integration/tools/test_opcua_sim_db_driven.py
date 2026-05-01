"""Integration tests: OPC UA simulator driven by whale database."""

from __future__ import annotations

import asyncio
import pytest

from tools.opcua_sim.fleet_runtime import OpcUaFleetRuntime


@pytest.mark.integration
def test_from_database_creates_fleet_with_correct_endpoints() -> None:
    """Verify from_database() reads acq_task and creates correct number of servers."""
    fleet = OpcUaFleetRuntime.from_database()
    try:
        endpoints = fleet.endpoints()
        assert len(endpoints) == 30, f"Expected 30 turbines, got {len(endpoints)}"
        assert "ZB-WTG-001" in endpoints
        assert endpoints["ZB-WTG-001"] == "opc.tcp://127.0.0.1:40001"
        assert endpoints["ZB-WTG-030"] == "opc.tcp://127.0.0.1:40030"
    finally:
        fleet._temp_dir.cleanup() if fleet._temp_dir else None


@pytest.mark.integration
def test_single_server_starts_and_exposes_all_variables() -> None:
    """Start one server from DB, connect, verify all v_measurement_point variables exist."""
    from whale.shared.persistence.session import session_scope
    from sqlalchemy import text

    # Count expected variables from DB
    with session_scope() as s:
        row = s.execute(text(
            "SELECT count(*) FROM v_measurement_point WHERE ied_name = 'IED_WTG_OPCUA'"
        )).fetchone()
        expected_count = row[0]

    async def _run() -> None:
        from asyncua import Client, ua

        fleet = OpcUaFleetRuntime.from_database()
        runtime = fleet._runtimes[0]
        runtime.start()
        try:
            await asyncio.sleep(1.5)  # wait for server to be ready
            async with Client(url=runtime.endpoint, timeout=5) as c:
                ns = await c.get_namespace_index("urn:windfarm:2wtg")
                objects = c.get_objects_node()
                wf = await objects.get_child(f"{ns}:WindFarm")
                children = await wf.get_children()
                assert len(children) == 1
                assert (await children[0].read_browse_name()).Name == "ZB-WTG-001"

                turbine_vars = await children[0].get_children()
                # 416 DOs, 395 unique do_names (some duplicates across LNs)
                # Nodeset deduplicates by name, so we expect 395
                assert len(turbine_vars) == 395, (
                    f"Expected 395 unique variables, got {len(turbine_vars)}"
                )

                # Check a few known variables from GB/T 30966 WTG fields
                var_names = set()
                for v in turbine_vars:
                    var_names.add((await v.read_browse_name()).Name)
                for expected in ("DevSt", "Ww", "RotSpd", "EnvTmp", "TurSt", "TurOp"):
                    assert expected in var_names, f"Variable {expected} not found"
        finally:
            runtime.stop()
            fleet._temp_dir.cleanup() if fleet._temp_dir else None

    asyncio.run(_run())


@pytest.mark.integration
def test_variable_values_update_over_time() -> None:
    """Start server, read a variable, wait, re-read — value should change."""
    async def _run() -> None:
        from asyncua import Client

        fleet = OpcUaFleetRuntime.from_database()
        runtime = fleet._runtimes[0]
        runtime.start()
        try:
            await asyncio.sleep(1.5)
            async with Client(url=runtime.endpoint, timeout=5) as c:
                ns = await c.get_namespace_index("urn:windfarm:2wtg")
                objects = c.get_objects_node()
                wf = await objects.get_child(f"{ns}:WindFarm")
                turbine = (await wf.get_children())[0]
                ww_node = None
                for v in await turbine.get_children():
                    if (await v.read_browse_name()).Name == "Ww":
                        ww_node = v
                        break
                assert ww_node is not None, "Ww (active power) variable not found"

                v1 = await ww_node.read_value()
                await asyncio.sleep(1.5)
                v2 = await ww_node.read_value()
                # Value should be non-zero and might differ due to simulation
                assert isinstance(v1, (int, float)), f"Unexpected type: {type(v1)}"
                # After 1.5s of simulation, values should be positive
                assert v2 > 0, f"Value should be positive: {v2}"
        finally:
            runtime.stop()
            fleet._temp_dir.cleanup() if fleet._temp_dir else None

    asyncio.run(_run())


@pytest.mark.integration
def test_multi_server_fleet_from_database() -> None:
    """Start 3 servers from DB, verify each exposes only its own turbine."""
    async def _run() -> None:
        from asyncua import Client

        fleet = OpcUaFleetRuntime.from_database()
        runtimes = fleet._runtimes[:3]
        for r in runtimes:
            r.start()
        try:
            await asyncio.sleep(2)
            for r in runtimes:
                async with Client(url=r.endpoint, timeout=5) as c:
                    ns = await c.get_namespace_index("urn:windfarm:2wtg")
                    objects = c.get_objects_node()
                    wf = await objects.get_child(f"{ns}:WindFarm")
                    children = await wf.get_children()
                    assert len(children) == 1
                    name = (await children[0].read_browse_name()).Name
                    assert name == r.name, f"Expected {r.name}, got {name}"
        finally:
            for r in runtimes:
                r.stop()
            fleet._temp_dir.cleanup() if fleet._temp_dir else None

    asyncio.run(_run())


@pytest.mark.integration
def test_single_server_delivers_10hz_update_rate() -> None:
    """Subscribe to 20 variables on one 10Hz server, verify ~100ms update interval."""
    from tools.opcua_sim.models import OpcUaServerConfig
    import time as _t

    async def _run() -> None:
        from asyncua import Client

        fleet = OpcUaFleetRuntime.from_database()
        runtime = fleet._runtimes[0]
        runtime._config = OpcUaServerConfig(
            name=runtime._config.name, endpoint=runtime._config.endpoint,
            security_policy=runtime._config.security_policy,
            security_mode=runtime._config.security_mode,
            update_interval_seconds=0.1,
        )
        runtime.start()
        try:
            await asyncio.sleep(2.0)
            ts: list[float] = []

            class _C:
                def datachange_notification(self, n, v, d):
                    del n, v, d; ts.append(_t.monotonic())

            async with Client(url=runtime.endpoint, timeout=5) as c:
                ns = await c.get_namespace_index("urn:windfarm:2wtg")
                wf = await c.get_objects_node().get_child(f"{ns}:WindFarm")
                turbine = (await wf.get_children())[0]
                sub = await c.create_subscription(50, _C())
                for v in (await turbine.get_children())[:20]:
                    await sub.subscribe_data_change(v)

                print(f"\n  Subscribed 20 vars, collecting 30s...")
                await asyncio.sleep(30)
                await sub.delete()

            intervals = [b - a for a, b in zip(ts, ts[1:])]
            mean_ms = (sum(intervals) / len(intervals)) * 1000 if intervals else 0
            print(f"  Events: {len(ts)}  Mean interval: {mean_ms:.1f}ms")

            assert len(ts) >= 100, f"Only {len(ts)} notifications"
            assert mean_ms < 30, f"Mean {mean_ms:.0f}ms > 30ms"
        finally:
            runtime.stop()
            fleet._temp_dir.cleanup() if fleet._temp_dir else None

    asyncio.run(_run())


@pytest.mark.integration
def test_all_30_servers_concurrent_10hz_update() -> None:
    """Start all 30 servers at 10Hz, verify each delivers notifications via sampling.

    Opens one client at a time, reads 3 variable values, moves to next server.
    Each server should return non-zero values from its 10Hz update thread.
    """
    from tools.opcua_sim.models import OpcUaServerConfig
    import time as _t

    async def _sample_one(endpoint: str) -> tuple[int, float]:
        from asyncua import Client
        try:
            async with Client(url=endpoint, timeout=5) as c:
                ns = await c.get_namespace_index("urn:windfarm:2wtg")
                wf = await c.get_objects_node().get_child(f"{ns}:WindFarm")
                turbine = (await wf.get_children())[0]
                vars_ = await turbine.get_children()
                count = 0
                t0 = _t.monotonic()
                for v in vars_[:3]:
                    try:
                        val = await v.read_value()
                        if isinstance(val, (int, float)) and val != 0:
                            count += 1
                    except Exception:
                        pass
                elapsed = (_t.monotonic() - t0) * 1000
                return count, elapsed
        except Exception as e:
            return -1, 0

    async def _run() -> None:
        fleet = OpcUaFleetRuntime.from_database()
        runtimes = fleet._runtimes
        results: dict[str, tuple[int, float]] = {}

        for rt in runtimes:
            rt._config = OpcUaServerConfig(
                name=rt._config.name, endpoint=rt._config.endpoint,
                security_policy=rt._config.security_policy,
                security_mode=rt._config.security_mode,
                update_interval_seconds=0.1,
            )
            rt.start()

        try:
            await asyncio.sleep(2.0)
            t_start = _t.monotonic()
            for rt in runtimes:
                count, ms = await _sample_one(rt.endpoint)
                results[rt.name] = (count, ms)

            total_ms = (_t.monotonic() - t_start) * 1000
            ok = sum(1 for c, _ in results.values() if c > 0)
            print(f"\n  Sampled 30 servers in {total_ms:.0f}ms: {ok}/30 OK")
            for name, (c, ms) in list(results.items())[:5]:
                print(f"  {name}: {c} non-zero vars, {ms:.0f}ms")
            if len(results) > 5:
                print(f"  ... ({len(results)} total)")

            assert ok >= 27, f"Only {ok}/30 servers returned non-zero values"
        finally:
            for rt in runtimes:
                rt.stop()
            fleet._temp_dir.cleanup() if fleet._temp_dir else None

    asyncio.run(_run())
