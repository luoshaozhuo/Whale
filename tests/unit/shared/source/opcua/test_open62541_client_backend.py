"""Unit tests for the open62541 OPC UA client backend helpers."""

from __future__ import annotations

import asyncio
import tempfile
from pathlib import Path

import pytest

from whale.shared.source.models import SourceConnectionProfile
from whale.shared.source.opcua.backends.base import Open62541PreparedReadPlan
from whale.shared.source.opcua.backends.open62541_backend import (
    Open62541OpcUaClientBackend,
    _normalize_open62541_node_id,
    resolve_client_runner_path,
)


class _FakeRunnerStdin:
    """Minimal async stdin writer used by runner-stream unit tests."""

    def __init__(self) -> None:
        self.writes: list[bytes] = []

    def write(self, data: bytes) -> None:
        self.writes.append(data)

    async def drain(self) -> None:
        return None


class _FakeRunner:
    """Minimal process stub exposing stdin/stdout attributes."""

    def __init__(self) -> None:
        self.stdin = _FakeRunnerStdin()
        self.stdout = object()
        self.returncode: int | None = None


def _connection() -> SourceConnectionProfile:
    """Build one minimal connection profile for open62541 backend tests."""

    return SourceConnectionProfile(
        endpoint="opc.tcp://127.0.0.1:4840",
        namespace_uri="urn:test:reader",
        timeout_seconds=0.1,
    )


def _prepared_backend_and_plan() -> tuple[Open62541OpcUaClientBackend, Open62541PreparedReadPlan]:
    """Build one connected backend with a cached prepared plan for unit tests."""

    backend = Open62541OpcUaClientBackend(_connection())
    backend._connected = True  # noqa: SLF001
    backend._nsidx = 2  # noqa: SLF001
    backend._runner = _FakeRunner()  # noqa: SLF001
    backend._temp_dir = tempfile.TemporaryDirectory(prefix="open62541_backend_test_")  # noqa: SLF001
    plan = backend.prepare_read(["s=IED001.LD0.WPPD1.TotW"])
    return backend, plan


@pytest.mark.unit
def test_resolve_client_runner_path_uses_env_override(monkeypatch: pytest.MonkeyPatch) -> None:
    """Environment override should control the runner executable path."""

    override = Path("/tmp/custom/open62541_client_reader").resolve()
    monkeypatch.setenv("WHALE_OPEN62541_CLIENT_RUNNER_PATH", str(override))

    assert resolve_client_runner_path() == override


@pytest.mark.unit
def test_connect_missing_runner_reports_absolute_path(monkeypatch: pytest.MonkeyPatch) -> None:
    """Missing runner errors should include the resolved path and build hint."""

    missing_runner = Path("/tmp/does-not-exist/open62541_client_reader").resolve()
    monkeypatch.setenv("WHALE_OPEN62541_CLIENT_RUNNER_PATH", str(missing_runner))

    backend = Open62541OpcUaClientBackend(_connection())

    with pytest.raises(RuntimeError, match="open62541_client_reader"):
        asyncio.run(backend.connect())

    with pytest.raises(RuntimeError, match=str(missing_runner)):
        asyncio.run(backend.connect())


@pytest.mark.unit
def test_prepare_read_normalizes_supported_node_id_forms() -> None:
    """prepare_read should normalize ns/s-prefixed node ids to string identifiers."""

    backend = Open62541OpcUaClientBackend(_connection())
    backend._connected = True  # noqa: SLF001
    backend._nsidx = 2  # noqa: SLF001
    backend._runner = object()  # type: ignore[assignment]  # noqa: SLF001
    backend._temp_dir = tempfile.TemporaryDirectory(prefix="open62541_backend_test_")  # noqa: SLF001

    plan = backend.prepare_read(
        [
            "ns=2;s=IED001.LD0.WPPD1.TotW",
            "nsu=urn:test:reader;s=IED001.LD0.WPPD1.OpCnt",
            "s=IED001.LD0.WPPD1.DevSt",
            "IED001.LD0.WPPD1.StrVal",
        ]
    )

    assert isinstance(plan, Open62541PreparedReadPlan)
    assert plan.node_ids == (
        "IED001.LD0.WPPD1.TotW",
        "IED001.LD0.WPPD1.OpCnt",
        "IED001.LD0.WPPD1.DevSt",
        "IED001.LD0.WPPD1.StrVal",
    )
    backend._temp_dir.cleanup()  # noqa: SLF001


@pytest.mark.unit
def test_prepare_read_accepts_tuple_addresses() -> None:
    """prepare_read should accept tuple inputs and still store tuple node ids."""

    backend = Open62541OpcUaClientBackend(_connection())
    backend._connected = True  # noqa: SLF001
    backend._nsidx = 2  # noqa: SLF001
    backend._runner = object()  # type: ignore[assignment]  # noqa: SLF001
    backend._temp_dir = tempfile.TemporaryDirectory(prefix="open62541_backend_test_")  # noqa: SLF001

    plan = backend.prepare_read(
        (
            "s=IED001.LD0.WPPD1.TotW",
            "IED001.LD0.WPPD1.OpCnt",
        )
    )

    assert plan.node_ids == (
        "IED001.LD0.WPPD1.TotW",
        "IED001.LD0.WPPD1.OpCnt",
    )
    backend._temp_dir.cleanup()  # noqa: SLF001


@pytest.mark.unit
def test_prepare_read_reuses_cached_plan_for_same_node_ids() -> None:
    """Repeated prepare_read calls should reuse the cached plan instance."""

    backend = Open62541OpcUaClientBackend(_connection())
    backend._connected = True  # noqa: SLF001
    backend._nsidx = 2  # noqa: SLF001
    backend._runner = object()  # type: ignore[assignment]  # noqa: SLF001
    backend._temp_dir = tempfile.TemporaryDirectory(prefix="open62541_backend_test_")  # noqa: SLF001

    first = backend.prepare_read(["s=IED001.LD0.WPPD1.TotW"])
    second = backend.prepare_read(["IED001.LD0.WPPD1.TotW"])

    assert first is second
    backend._temp_dir.cleanup()  # noqa: SLF001


@pytest.mark.unit
def test_normalize_open62541_node_id_variants() -> None:
    """The low-level node-id helper should preserve logical string ids."""

    assert _normalize_open62541_node_id("ns=2;s=A.B.C") == "A.B.C"
    assert _normalize_open62541_node_id("nsu=urn:test;s=A.B.C") == "A.B.C"
    assert _normalize_open62541_node_id("s=A.B.C") == "A.B.C"
    assert _normalize_open62541_node_id("A.B.C") == "A.B.C"


@pytest.mark.unit
def test_parse_result_line_accepts_ok_payload() -> None:
    """A valid RESULT line should parse into one typed summary object."""

    backend = Open62541OpcUaClientBackend(_connection())

    summary = backend._parse_result_line(  # noqa: SLF001
        "RESULT\tplan_0\tOK\t416\t1715731200000\t-",
        expected_plan_id="plan_0",
        command_timing=None,
    )

    assert summary.ok is True
    assert summary.value_count == 416
    assert summary.response_timestamp is not None


@pytest.mark.unit
def test_parse_result_line_accepts_error_payload() -> None:
    """ERROR payloads should parse into failed summaries without crashing."""

    backend = Open62541OpcUaClientBackend(_connection())

    summary = backend._parse_result_line(  # noqa: SLF001
        "RESULT\tplan_0\tERROR\t0\t0\tservice_failed",
        expected_plan_id="plan_0",
        command_timing=None,
    )

    assert summary.ok is False
    assert summary.value_count == 0
    assert summary.response_timestamp is None
    assert summary.error_reason == "read_failed"
    assert summary.exception == "service_failed"


@pytest.mark.unit
def test_parse_result_line_rejects_plan_id_mismatch() -> None:
    """Runner responses should match the plan id requested by Python."""

    backend = Open62541OpcUaClientBackend(_connection())

    with pytest.raises(RuntimeError, match="Mismatched plan id"):
        backend._parse_result_line(  # noqa: SLF001
            "RESULT\tplan_1\tOK\t1\t1715731200000\t-",
            expected_plan_id="plan_0",
            command_timing=None,
        )


@pytest.mark.unit
def test_parse_result_line_rejects_malformed_payload() -> None:
    """Malformed RESULT lines should fail clearly instead of being half-parsed."""

    backend = Open62541OpcUaClientBackend(_connection())

    with pytest.raises(RuntimeError, match="Unexpected read response"):
        backend._parse_result_line(  # noqa: SLF001
            "RESULT\tplan_0\tOK\t1",
            expected_plan_id="plan_0",
            command_timing=None,
        )


@pytest.mark.unit
def test_parse_result_line_rejects_invalid_numeric_fields() -> None:
    """Numeric protocol fields should be validated explicitly."""

    backend = Open62541OpcUaClientBackend(_connection())

    with pytest.raises(RuntimeError, match="value_count"):
        backend._parse_result_line(  # noqa: SLF001
            "RESULT\tplan_0\tOK\tnan\t1715731200000\t-",
            expected_plan_id="plan_0",
            command_timing=None,
        )


@pytest.mark.unit
def test_parse_result_line_rejects_unknown_status() -> None:
    """Only OK and ERROR statuses should be accepted from the runner."""

    backend = Open62541OpcUaClientBackend(_connection())

    with pytest.raises(RuntimeError, match="Unexpected read status"):
        backend._parse_result_line(  # noqa: SLF001
            "RESULT\tplan_0\tERR\t1\t1715731200000\t-",
            expected_plan_id="plan_0",
            command_timing=None,
        )


@pytest.mark.unit
def test_parse_result_stream_line_accepts_ok_payload() -> None:
    """A valid RESULT_STREAM line should expose runner-side polling timings."""

    backend = Open62541OpcUaClientBackend(_connection())

    result = backend._parse_result_stream_line(  # noqa: SLF001
        (
            "RESULT_STREAM\tplan_0\t7\tOK\t416\t1715731200000\t-\t"
            "1000000000\t1000100000\t1000200000\t1000300000"
        ),
        expected_plan_id="plan_0",
        stdout_line_received_ts_ns=1000400000,
    )

    assert result.seq == 7
    assert result.ok is True
    assert result.value_count == 416
    assert result.response_timestamp is not None
    assert result.debug_timing is not None
    assert result.debug_timing.runner_scheduled_ts_ns == 1000000000
    assert result.debug_timing.runner_response_write_ts_ns == 1000300000


@pytest.mark.unit
def test_parse_poll_terminal_line_validates_plan_id() -> None:
    """Polling terminal control lines should validate the expected plan id."""

    backend = Open62541OpcUaClientBackend(_connection())

    with pytest.raises(RuntimeError, match="Mismatched plan id"):
        backend._parse_poll_terminal_line(  # noqa: SLF001
            "POLL_DONE\tplan_1\t12\t12\t0",
            expected_prefix="POLL_DONE",
            expected_plan_id="plan_0",
        )


@pytest.mark.unit
def test_stream_prepared_raw_poll_cancel_sends_stop_poll() -> None:
    """Closing the polling stream early should send STOP_POLL and accept POLL_STOPPED."""

    async def scenario() -> None:
        backend, plan = _prepared_backend_and_plan()
        protocol_lines = iter(
            (
                "POLL_STARTED\tplan_0\t10.000000000\t1.000000000\t2.000000000",
                (
                    "RESULT_STREAM\tplan_0\t0\tOK\t1\t1715731200000\t-\t"
                    "1000000000\t1000100000\t1000200000\t1000300000"
                ),
                "POLL_STOPPED\tplan_0\t1\t1\t0",
            )
        )

        async def fake_read_protocol_line(
            *,
            expected_prefixes: tuple[str, ...],
            timeout_seconds: float,
        ) -> str:
            del expected_prefixes, timeout_seconds
            backend._last_stdout_line_received_ts_ns = 1000400000  # noqa: SLF001
            return next(protocol_lines)

        backend._read_protocol_line = fake_read_protocol_line  # type: ignore[method-assign]  # noqa: SLF001
        backend._ensure_remote_plan = lambda _plan: asyncio.sleep(0)  # type: ignore[method-assign]  # noqa: SLF001

        stream = backend.stream_prepared_raw_poll(
            plan,
            target_hz=10.0,
            warmup_s=1.0,
            duration_s=2.0,
        )
        first = await anext(stream)
        assert first.seq == 0

        await stream.aclose()

        runner = backend._runner  # noqa: SLF001
        assert isinstance(runner, _FakeRunner)
        writes = [item.decode("utf-8") for item in runner.stdin.writes]
        assert any(item.startswith("STOP_POLL\tplan_0\n") for item in writes)
        backend._temp_dir.cleanup()  # noqa: SLF001

    asyncio.run(scenario())


@pytest.mark.unit
def test_stream_prepared_raw_poll_done_does_not_send_stop_poll() -> None:
    """Natural POLL_DONE completion should not trigger a STOP_POLL cleanup write."""

    async def scenario() -> None:
        backend, plan = _prepared_backend_and_plan()
        protocol_lines = iter(
            (
                "POLL_STARTED\tplan_0\t10.000000000\t1.000000000\t2.000000000",
                (
                    "RESULT_STREAM\tplan_0\t0\tOK\t1\t1715731200000\t-\t"
                    "1000000000\t1000100000\t1000200000\t1000300000"
                ),
                "POLL_DONE\tplan_0\t1\t1\t0",
            )
        )

        async def fake_read_protocol_line(
            *,
            expected_prefixes: tuple[str, ...],
            timeout_seconds: float,
        ) -> str:
            del expected_prefixes, timeout_seconds
            backend._last_stdout_line_received_ts_ns = 1000400000  # noqa: SLF001
            return next(protocol_lines)

        backend._read_protocol_line = fake_read_protocol_line  # type: ignore[method-assign]  # noqa: SLF001
        backend._ensure_remote_plan = lambda _plan: asyncio.sleep(0)  # type: ignore[method-assign]  # noqa: SLF001

        results = [
            item
            async for item in backend.stream_prepared_raw_poll(
                plan,
                target_hz=10.0,
                warmup_s=1.0,
                duration_s=2.0,
            )
        ]

        assert len(results) == 1
        runner = backend._runner  # noqa: SLF001
        assert isinstance(runner, _FakeRunner)
        writes = [item.decode("utf-8") for item in runner.stdin.writes]
        assert not any(item.startswith("STOP_POLL\tplan_0\n") for item in writes)
        backend._temp_dir.cleanup()  # noqa: SLF001

    asyncio.run(scenario())


@pytest.mark.unit
def test_stream_prepared_raw_poll_cancel_accepts_poll_done_terminal_line() -> None:
    """Early stream close should also tolerate POLL_DONE in place of POLL_STOPPED."""

    async def scenario() -> None:
        backend, plan = _prepared_backend_and_plan()
        protocol_lines = iter(
            (
                "POLL_STARTED\tplan_0\t10.000000000\t1.000000000\t2.000000000",
                (
                    "RESULT_STREAM\tplan_0\t0\tOK\t1\t1715731200000\t-\t"
                    "1000000000\t1000100000\t1000200000\t1000300000"
                ),
                "POLL_DONE\tplan_0\t1\t1\t0",
            )
        )

        async def fake_read_protocol_line(
            *,
            expected_prefixes: tuple[str, ...],
            timeout_seconds: float,
        ) -> str:
            del expected_prefixes, timeout_seconds
            backend._last_stdout_line_received_ts_ns = 1000400000  # noqa: SLF001
            return next(protocol_lines)

        backend._read_protocol_line = fake_read_protocol_line  # type: ignore[method-assign]  # noqa: SLF001
        backend._ensure_remote_plan = lambda _plan: asyncio.sleep(0)  # type: ignore[method-assign]  # noqa: SLF001

        stream = backend.stream_prepared_raw_poll(
            plan,
            target_hz=10.0,
            warmup_s=1.0,
            duration_s=2.0,
        )
        _ = await anext(stream)
        await stream.aclose()

        runner = backend._runner  # noqa: SLF001
        assert isinstance(runner, _FakeRunner)
        writes = [item.decode("utf-8") for item in runner.stdin.writes]
        assert any(item.startswith("STOP_POLL\tplan_0\n") for item in writes)
        backend._temp_dir.cleanup()  # noqa: SLF001

    asyncio.run(scenario())


@pytest.mark.unit
def test_read_protocol_line_ignores_non_protocol_logs() -> None:
    """Protocol reads should skip runner log noise until a protocol prefix appears."""

    backend = Open62541OpcUaClientBackend(_connection())
    lines = iter(
        (
            "[log]\tnoise",
            "READY\t2",
        )
    )

    async def _fake_read_stdout_line(*, timeout_seconds: float) -> str:
        return next(lines)

    backend._read_stdout_line = _fake_read_stdout_line  # type: ignore[method-assign]  # noqa: SLF001

    result = asyncio.run(
        backend._read_protocol_line(  # noqa: SLF001
            expected_prefixes=("READY",),
            timeout_seconds=1.0,
        )
    )

    assert result == "READY\t2"
