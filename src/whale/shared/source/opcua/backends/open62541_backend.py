from __future__ import annotations

import asyncio
import os
import tempfile
import time
from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Final

from whale.shared.source.models import SourceConnectionProfile
from whale.shared.source.opcua.backends.base import (
    Open62541PreparedReadPlan,
    PreparedReadPlan,
    RawDataValue,
    RawOpcUaReadResult,
)

_CONNECT_TIMEOUT_FACTOR: Final[float] = 2.0
_PROCESS_STOP_TIMEOUT_S: Final[float] = 2.0
_PREPARE_RESPONSE_PREFIX: Final[str] = "PREPARED"
_READY_RESPONSE_PREFIX: Final[str] = "READY"
_RESULT_RESPONSE_PREFIX: Final[str] = "RESULT"
_RESULT_STREAM_RESPONSE_PREFIX: Final[str] = "RESULT_STREAM"
_POLL_STARTED_RESPONSE_PREFIX: Final[str] = "POLL_STARTED"
_POLL_DONE_RESPONSE_PREFIX: Final[str] = "POLL_DONE"
_POLL_STOPPED_RESPONSE_PREFIX: Final[str] = "POLL_STOPPED"


@dataclass(frozen=True, slots=True)
class Open62541ReadDebugTiming:
    """Cross-process timing for one open62541 runner read command.

    All fields use monotonic nanoseconds. On Linux, Python ``time.monotonic_ns()``
    and C ``clock_gettime(CLOCK_MONOTONIC)`` are comparable on the same host,
    so the profile test may estimate pipe-return delay from these fields.
    """

    command_write_ts_ns: int | None = None
    command_drain_done_ts_ns: int | None = None
    stdout_line_received_ts_ns: int | None = None
    runner_request_received_ts_ns: int | None = None
    runner_scheduled_ts_ns: int | None = None
    runner_read_start_ts_ns: int | None = None
    runner_read_end_ts_ns: int | None = None
    runner_response_write_ts_ns: int | None = None


@dataclass(frozen=True, slots=True)
class _PreparedPlanRuntime:
    """Runtime metadata stored alongside one prepared open62541 read plan."""

    plan_id: str
    node_ids_path: Path


@dataclass(frozen=True, slots=True)
class _CommandTiming:
    """Python-side pipe timing for one runner command."""

    command_write_ts_ns: int
    command_drain_done_ts_ns: int
    stdout_line_received_ts_ns: int | None


@dataclass(frozen=True, slots=True)
class _RunnerReadSummary:
    """Parsed one-line summary returned by the open62541 client runner."""

    ok: bool
    value_count: int
    response_timestamp: datetime | None
    error_reason: str | None = None
    exception: str | None = None
    debug_timing: Open62541ReadDebugTiming | None = None


@dataclass(frozen=True, slots=True)
class Open62541StreamReadResult:
    """One streamed raw read result emitted by internal runner polling."""

    seq: int
    ok: bool
    value_count: int
    response_timestamp: datetime | None
    detail: str | None = None
    debug_timing: Open62541ReadDebugTiming | None = None


@dataclass(frozen=True, slots=True)
class _PollControlSummary:
    """Parsed START/STOP/DONE control line from the runner polling protocol."""

    plan_id: str
    total_ticks: int | None = None
    ok_count: int | None = None
    error_count: int | None = None


def resolve_client_runner_path() -> Path:
    """Resolve the open62541 client runner executable path."""

    env_path = os.environ.get("WHALE_OPEN62541_CLIENT_RUNNER_PATH")
    if env_path:
        return Path(env_path).expanduser().resolve()

    source_lab_root = Path(__file__).resolve().parents[6] / "tools" / "source_lab"
    suffix = ".exe" if os.name == "nt" else ""
    return source_lab_root / "native" / "build" / f"open62541_client_runner{suffix}"


def _normalize_open62541_node_id(address: str) -> str:
    """Normalize one address to the string node id expected by the client runner."""

    if address.startswith("ns=") and ";s=" in address:
        return address.split(";s=", 1)[1]
    if address.startswith("nsu=") and ";s=" in address:
        return address.split(";s=", 1)[1]
    if address.startswith("s="):
        return address[2:]
    return address


def _datetime_from_unix_ms(value: str) -> datetime | None:
    """Convert one unix-millisecond string to UTC datetime when present."""

    try:
        unix_ms = int(value)
    except ValueError:
        return None

    if unix_ms <= 0:
        return None
    return datetime.fromtimestamp(unix_ms / 1000.0, tz=timezone.utc)


def _parse_runner_int(field_name: str, value: str) -> int:
    """Parse one integer field from the runner protocol."""

    try:
        return int(value)
    except ValueError as exc:
        raise RuntimeError(
            f"Invalid {field_name} field in open62541 runner response: {value!r}"
        ) from exc


def _parse_runner_optional_ns(field_name: str, value: str) -> int | None:
    """Parse one optional monotonic-ns timing field from the runner protocol."""

    if value in {"", "-", "0"}:
        return None
    parsed = _parse_runner_int(field_name, value)
    return parsed if parsed > 0 else None


class Open62541OpcUaClientBackend:
    """open62541-based OPC UA client backend for raw polling.

    This backend uses a small persistent C runner process. It currently focuses
    on raw polling for load tests and only returns backend-neutral
    ``RawDataValue`` markers sized to the number of values reported by the
    runner. The full Batch path remains asyncua-only in ``reader.py``.
    """

    def __init__(self, connection: SourceConnectionProfile) -> None:
        """Initialize one open62541 raw-polling backend."""

        self._connection = connection
        self._connected = False
        self._nsidx: int | None = None
        self._runner: asyncio.subprocess.Process | None = None
        self._temp_dir: tempfile.TemporaryDirectory[str] | None = None
        self._read_plan_cache: dict[tuple[str, ...], Open62541PreparedReadPlan] = {}
        self._read_plan_runtime: dict[tuple[str, ...], _PreparedPlanRuntime] = {}
        self._prepared_remote_plan_ids: set[str] = set()
        self._io_lock = asyncio.Lock()
        self._last_stdout_line_received_ts_ns: int | None = None
        self._last_read_debug_timing: Open62541ReadDebugTiming | None = None

    async def connect(self) -> None:
        """Start the open62541 client runner and establish one OPC UA connection."""

        if self._connected:
            return

        runner_path = resolve_client_runner_path()
        if not runner_path.exists():
            raise RuntimeError(
                "open62541 client runner executable does not exist: "
                f"{runner_path}. Build `open62541_client_runner` first with CMake."
            )

        self._temp_dir = tempfile.TemporaryDirectory(prefix="open62541_client_runner_")
        timeout_ms = max(1, round(self._connection.timeout_seconds * 1000.0))
        namespace_uri = self._connection.namespace_uri or "-"

        self._runner = await asyncio.create_subprocess_exec(
            str(runner_path),
            self._connection.endpoint,
            namespace_uri,
            str(timeout_ms),
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        try:
            ready_line = await self._read_protocol_line(
                expected_prefixes=(_READY_RESPONSE_PREFIX,),
                timeout_seconds=max(self._connection.timeout_seconds * _CONNECT_TIMEOUT_FACTOR, 1.0),
            )
            fields = ready_line.split("\t")
            if len(fields) != 2 or fields[0] != _READY_RESPONSE_PREFIX:
                raise RuntimeError(f"Unexpected runner ready response: {ready_line!r}")

            self._nsidx = int(fields[1])
            self._connected = True
        except Exception:
            await self.disconnect()
            raise

    async def disconnect(self) -> None:
        """Stop the client runner process and drop cached prepared plans."""

        runner = self._runner
        self._runner = None

        if runner is not None:
            try:
                if runner.returncode is None and runner.stdin is not None:
                    runner.stdin.write(b"QUIT\n")
                    await runner.stdin.drain()
            except (BrokenPipeError, ConnectionResetError):
                pass
            except RuntimeError:
                pass

            try:
                await asyncio.wait_for(runner.wait(), timeout=_PROCESS_STOP_TIMEOUT_S)
            except asyncio.TimeoutError:
                runner.terminate()
                try:
                    await asyncio.wait_for(runner.wait(), timeout=_PROCESS_STOP_TIMEOUT_S)
                except asyncio.TimeoutError:
                    runner.kill()
                    await runner.wait()

        if self._temp_dir is not None:
            self._temp_dir.cleanup()
            self._temp_dir = None

        self._connected = False
        self._nsidx = None
        self._read_plan_cache.clear()
        self._read_plan_runtime.clear()
        self._prepared_remote_plan_ids.clear()
        self._last_stdout_line_received_ts_ns = None
        self._last_read_debug_timing = None

    @property
    def namespace_index(self) -> int | None:
        """Return resolved namespace index from the connected runner."""

        return self._nsidx

    @property
    def last_read_debug_timing(self) -> Open62541ReadDebugTiming | None:
        """Return timing captured for the latest raw read command."""

        return self._last_read_debug_timing

    def prepare_read(self, addresses: Sequence[str]) -> Open62541PreparedReadPlan:
        """Prepare one reusable raw-polling plan without network traffic."""

        self._ensure_connected()
        if self._temp_dir is None:
            raise RuntimeError("open62541 client runner temp directory is not initialized")

        normalized_node_ids = tuple(_normalize_open62541_node_id(address) for address in addresses)
        cache_key = tuple(normalized_node_ids)

        cached = self._read_plan_cache.get(cache_key)
        if cached is not None:
            return cached

        plan = Open62541PreparedReadPlan(
            node_paths=cache_key,
            node_ids=cache_key,
            namespace_uri=self._connection.namespace_uri,
            namespace_index=self._nsidx,
        )

        plan_id = f"plan_{len(self._read_plan_cache)}"
        node_ids_path = Path(self._temp_dir.name) / f"{plan_id}.tsv"
        node_ids_path.write_text("\n".join(plan.node_ids) + "\n", encoding="utf-8")

        self._read_plan_cache[cache_key] = plan
        self._read_plan_runtime[cache_key] = _PreparedPlanRuntime(
            plan_id=plan_id,
            node_ids_path=node_ids_path,
        )
        return plan

    async def read_prepared_raw(
        self,
        plan: PreparedReadPlan,
    ) -> RawOpcUaReadResult:
        """Read prepared values through the open62541 client runner."""

        open62541_plan = self._require_plan_type(plan)
        retry_count = 0
        max_retries = 1

        while retry_count <= max_retries:
            try:
                summary = await self._read_summary(open62541_plan)
                self._last_read_debug_timing = summary.debug_timing
                if not summary.ok:
                    raise RuntimeError(summary.exception or summary.error_reason or "read_failed")

                data_values = tuple(RawDataValue(value=True) for _ in range(summary.value_count))
                return RawOpcUaReadResult(
                    ok=True,
                    data_values=data_values,
                    response_timestamp=summary.response_timestamp,
                    retry_count=retry_count,
                )
            except asyncio.TimeoutError as ex:
                retry_count += 1
                if retry_count > max_retries:
                    return RawOpcUaReadResult(
                        ok=False,
                        data_values=(),
                        response_timestamp=None,
                        error_reason="timeout",
                        exception=str(ex),
                        retry_count=retry_count,
                    )
                await asyncio.sleep(0.05)
            except Exception as ex:
                retry_count += 1
                if retry_count > max_retries:
                    return RawOpcUaReadResult(
                        ok=False,
                        data_values=(),
                        response_timestamp=None,
                        error_reason="read_failed",
                        exception=str(ex),
                        retry_count=retry_count,
                    )
                await asyncio.sleep(0.05)

        return RawOpcUaReadResult(
            ok=False,
            data_values=(),
            response_timestamp=None,
            error_reason="read_failed",
            retry_count=max_retries + 1,
        )

    async def stream_prepared_raw_poll(
        self,
        plan: PreparedReadPlan,
        *,
        target_hz: float,
        warmup_s: float,
        duration_s: float,
    ) -> AsyncIterator[Open62541StreamReadResult]:
        """Stream fixed-rate raw reads executed inside the open62541 runner.

        Args:
            plan: Prepared open62541 read plan previously returned by ``prepare_read``.
            target_hz: Fixed polling frequency executed by the C runner.
            warmup_s: Warmup duration executed before Python keeps samples.
            duration_s: Measurement duration executed after warmup.

        Yields:
            One ``Open62541StreamReadResult`` per C-side tick until ``POLL_DONE``.
        """

        if target_hz <= 0:
            raise ValueError("target_hz must be greater than 0")
        if warmup_s < 0:
            raise ValueError("warmup_s must be greater than or equal to 0")
        if duration_s <= 0:
            raise ValueError("duration_s must be greater than 0")

        open62541_plan = self._require_plan_type(plan)
        await self._ensure_remote_plan(open62541_plan)
        runtime = self._runtime_for_plan(open62541_plan)
        line_timeout_seconds = max(
            self._connection.timeout_seconds,
            (1.0 / target_hz) * 4.0,
            1.0,
        )

        async with self._io_lock:
            self._ensure_connected()
            runner = self._runner
            assert runner is not None
            if runner.stdin is None or runner.stdout is None:
                raise RuntimeError("open62541 client runner pipes are unavailable")

            poll_finished = False
            runner.stdin.write(
                (
                    f"START_POLL\t{runtime.plan_id}\t{target_hz:.9f}\t"
                    f"{warmup_s:.9f}\t{duration_s:.9f}\n"
                ).encode("utf-8")
            )
            await runner.stdin.drain()
            started_line = await self._read_protocol_line(
                expected_prefixes=(_POLL_STARTED_RESPONSE_PREFIX, "ERROR"),
                timeout_seconds=line_timeout_seconds,
            )
            self._parse_poll_started_line(started_line, expected_plan_id=runtime.plan_id)

            try:
                while True:
                    line = await self._read_protocol_line(
                        expected_prefixes=(
                            _RESULT_STREAM_RESPONSE_PREFIX,
                            _POLL_DONE_RESPONSE_PREFIX,
                            "ERROR",
                        ),
                        timeout_seconds=line_timeout_seconds,
                    )
                    if line.startswith(_RESULT_STREAM_RESPONSE_PREFIX):
                        result = self._parse_result_stream_line(
                            line,
                            expected_plan_id=runtime.plan_id,
                            stdout_line_received_ts_ns=self._last_stdout_line_received_ts_ns,
                        )
                        self._last_read_debug_timing = result.debug_timing
                        yield result
                        continue

                    if line.startswith(_POLL_DONE_RESPONSE_PREFIX):
                        self._parse_poll_terminal_line(
                            line,
                            expected_prefix=_POLL_DONE_RESPONSE_PREFIX,
                            expected_plan_id=runtime.plan_id,
                        )
                        poll_finished = True
                        break

                    raise RuntimeError(f"Unexpected polling response from runner: {line!r}")
            finally:
                if not poll_finished and runner.returncode is None and runner.stdin is not None:
                    try:
                        runner.stdin.write(f"STOP_POLL\t{runtime.plan_id}\n".encode("utf-8"))
                        await runner.stdin.drain()
                        stop_line = await self._read_protocol_line(
                            expected_prefixes=(
                                _POLL_STOPPED_RESPONSE_PREFIX,
                                _POLL_DONE_RESPONSE_PREFIX,
                            ),
                            timeout_seconds=line_timeout_seconds,
                        )
                        expected_prefix = (
                            _POLL_STOPPED_RESPONSE_PREFIX
                            if stop_line.startswith(_POLL_STOPPED_RESPONSE_PREFIX)
                            else _POLL_DONE_RESPONSE_PREFIX
                        )
                        self._parse_poll_terminal_line(
                            stop_line,
                            expected_prefix=expected_prefix,
                            expected_plan_id=runtime.plan_id,
                        )
                    except Exception:
                        # Best-effort cleanup only. The caller will still disconnect on failure.
                        pass

    def _ensure_connected(self) -> None:
        """Ensure the backend runner is available before a command is issued."""

        if not self._connected or self._runner is None:
            raise RuntimeError("open62541 OPC UA client backend is not connected")

    def _require_plan_type(self, plan: PreparedReadPlan) -> Open62541PreparedReadPlan:
        """Validate that the caller supplied an open62541-specific prepared plan."""

        if not isinstance(plan, Open62541PreparedReadPlan):
            raise TypeError("Open62541OpcUaClientBackend requires Open62541PreparedReadPlan")
        return plan

    async def _read_summary(self, plan: Open62541PreparedReadPlan) -> _RunnerReadSummary:
        """Ensure one plan is prepared in the runner, then execute one read."""

        await self._ensure_remote_plan(plan)
        runtime = self._runtime_for_plan(plan)
        line, command_timing = await self._run_command(
            f"READ\t{runtime.plan_id}\n".encode("utf-8"),
            expected_prefixes=(_RESULT_RESPONSE_PREFIX,),
        )
        return self._parse_result_line(
            line,
            expected_plan_id=runtime.plan_id,
            command_timing=command_timing,
        )

    async def _ensure_remote_plan(self, plan: Open62541PreparedReadPlan) -> None:
        """Upload one cached plan to the runner once per backend lifetime."""

        runtime = self._runtime_for_plan(plan)
        if runtime.plan_id in self._prepared_remote_plan_ids:
            return

        node_ids_path = str(runtime.node_ids_path).replace("\n", "").replace("\r", "")
        line, _ = await self._run_command(
            f"PREPARE\t{runtime.plan_id}\t{node_ids_path}\n".encode("utf-8"),
            expected_prefixes=(_PREPARE_RESPONSE_PREFIX, "ERROR"),
        )
        fields = line.split("\t")
        if len(fields) != 3 or fields[0] != _PREPARE_RESPONSE_PREFIX or fields[1] != runtime.plan_id:
            raise RuntimeError(f"Unexpected prepare response from runner: {line!r}")
        self._prepared_remote_plan_ids.add(runtime.plan_id)

    def _runtime_for_plan(self, plan: Open62541PreparedReadPlan) -> _PreparedPlanRuntime:
        """Return cached runtime metadata for one prepared plan."""

        runtime = self._read_plan_runtime.get(plan.node_paths)
        if runtime is None:
            raise RuntimeError("Prepared open62541 plan runtime metadata is missing")
        return runtime

    async def _run_command(
        self,
        command: bytes,
        *,
        expected_prefixes: tuple[str, ...],
    ) -> tuple[str, _CommandTiming]:
        """Write one command and read one response line under a single IO lock."""

        self._ensure_connected()
        runner = self._runner
        assert runner is not None
        if runner.stdin is None or runner.stdout is None:
            raise RuntimeError("open62541 client runner pipes are unavailable")

        async with self._io_lock:
            command_write_ts_ns = time.monotonic_ns()
            runner.stdin.write(command)
            await runner.stdin.drain()
            command_drain_done_ts_ns = time.monotonic_ns()
            line = await self._read_protocol_line(
                expected_prefixes=expected_prefixes,
                timeout_seconds=self._connection.timeout_seconds,
            )
            return line, _CommandTiming(
                command_write_ts_ns=command_write_ts_ns,
                command_drain_done_ts_ns=command_drain_done_ts_ns,
                stdout_line_received_ts_ns=self._last_stdout_line_received_ts_ns,
            )

    async def _read_stdout_line(self, *, timeout_seconds: float) -> str:
        """Read one stdout line from the runner with timeout and liveness checks."""

        runner = self._runner
        if runner is None:
            raise RuntimeError("open62541 client runner process is not started")
        if runner.stdout is None:
            raise RuntimeError("open62541 client runner stdout is unavailable")

        line = await asyncio.wait_for(runner.stdout.readline(), timeout=timeout_seconds)
        self._last_stdout_line_received_ts_ns = time.monotonic_ns()
        if not line:
            stderr_text = await self._read_stderr_text()
            raise RuntimeError(
                "open62541 client runner exited unexpectedly"
                + (f": {stderr_text}" if stderr_text else "")
            )
        return line.decode("utf-8").strip()

    async def _read_protocol_line(
        self,
        *,
        expected_prefixes: tuple[str, ...],
        timeout_seconds: float,
    ) -> str:
        """Read protocol output and ignore non-protocol runner log lines."""

        deadline = time.perf_counter() + timeout_seconds
        while True:
            remaining = deadline - time.perf_counter()
            if remaining <= 0:
                raise asyncio.TimeoutError(
                    f"Timed out waiting for runner response prefixes={expected_prefixes!r}"
                )

            line = await self._read_stdout_line(timeout_seconds=remaining)
            if any(line.startswith(prefix) for prefix in expected_prefixes):
                return line

    async def _read_stderr_text(self) -> str:
        """Best-effort read of available runner stderr for diagnostics."""

        runner = self._runner
        if runner is None or runner.stderr is None:
            return ""

        try:
            chunk = await asyncio.wait_for(runner.stderr.read(), timeout=0.1)
        except asyncio.TimeoutError:
            return ""
        return chunk.decode("utf-8", errors="replace").strip()

    def _parse_result_line(
        self,
        line: str,
        *,
        expected_plan_id: str,
        command_timing: _CommandTiming | None = None,
    ) -> _RunnerReadSummary:
        """Parse one ``RESULT`` line emitted by the client runner.

        Supported protocol versions:
        ``RESULT<TAB>plan_id<TAB>OK|ERROR<TAB>value_count<TAB>timestamp_ms<TAB>detail``

        ``RESULT<TAB>plan_id<TAB>OK|ERROR<TAB>value_count<TAB>timestamp_ms<TAB>detail``
        ``<TAB>request_received_ns<TAB>read_start_ns<TAB>read_end_ns<TAB>response_write_ns``
        """

        fields = line.split("\t")
        if len(fields) not in {6, 10} or fields[0] != _RESULT_RESPONSE_PREFIX:
            raise RuntimeError(f"Unexpected read response from runner: {line!r}")
        if fields[1] != expected_plan_id:
            raise RuntimeError(
                "Mismatched plan id in runner response: "
                f"expected={expected_plan_id!r}, got={fields[1]!r}"
            )

        status = fields[2]
        if status not in {"OK", "ERROR"}:
            raise RuntimeError(f"Unexpected read status from runner: {status!r}")

        ok = status == "OK"
        value_count = _parse_runner_int("value_count", fields[3])
        response_timestamp = _datetime_from_unix_ms(fields[4])
        detail = None if fields[5] == "-" else fields[5]

        runner_request_received_ts_ns: int | None = None
        runner_read_start_ts_ns: int | None = None
        runner_read_end_ts_ns: int | None = None
        runner_response_write_ts_ns: int | None = None
        if len(fields) == 10:
            runner_request_received_ts_ns = _parse_runner_optional_ns(
                "runner_request_received_ts_ns", fields[6]
            )
            runner_read_start_ts_ns = _parse_runner_optional_ns(
                "runner_read_start_ts_ns", fields[7]
            )
            runner_read_end_ts_ns = _parse_runner_optional_ns(
                "runner_read_end_ts_ns", fields[8]
            )
            runner_response_write_ts_ns = _parse_runner_optional_ns(
                "runner_response_write_ts_ns", fields[9]
            )

        debug_timing = Open62541ReadDebugTiming(
            command_write_ts_ns=(
                command_timing.command_write_ts_ns if command_timing is not None else None
            ),
            command_drain_done_ts_ns=(
                command_timing.command_drain_done_ts_ns if command_timing is not None else None
            ),
            stdout_line_received_ts_ns=(
                command_timing.stdout_line_received_ts_ns if command_timing is not None else None
            ),
            runner_request_received_ts_ns=runner_request_received_ts_ns,
            runner_read_start_ts_ns=runner_read_start_ts_ns,
            runner_read_end_ts_ns=runner_read_end_ts_ns,
            runner_response_write_ts_ns=runner_response_write_ts_ns,
        )

        return _RunnerReadSummary(
            ok=ok,
            value_count=value_count,
            response_timestamp=response_timestamp,
            error_reason=None if ok else "read_failed",
            exception=detail,
            debug_timing=debug_timing,
        )

    def _parse_result_stream_line(
        self,
        line: str,
        *,
        expected_plan_id: str,
        stdout_line_received_ts_ns: int | None,
    ) -> Open62541StreamReadResult:
        """Parse one ``RESULT_STREAM`` line emitted by runner-internal polling."""

        fields = line.split("\t")
        if len(fields) != 11 or fields[0] != _RESULT_STREAM_RESPONSE_PREFIX:
            raise RuntimeError(f"Unexpected stream read response from runner: {line!r}")
        if fields[1] != expected_plan_id:
            raise RuntimeError(
                "Mismatched plan id in runner stream response: "
                f"expected={expected_plan_id!r}, got={fields[1]!r}"
            )

        status = fields[3]
        if status not in {"OK", "ERROR"}:
            raise RuntimeError(f"Unexpected stream read status from runner: {status!r}")

        detail = None if fields[6] == "-" else fields[6]
        debug_timing = Open62541ReadDebugTiming(
            stdout_line_received_ts_ns=stdout_line_received_ts_ns,
            runner_scheduled_ts_ns=_parse_runner_optional_ns("scheduled_ts_ns", fields[7]),
            runner_read_start_ts_ns=_parse_runner_optional_ns("read_start_ts_ns", fields[8]),
            runner_read_end_ts_ns=_parse_runner_optional_ns("read_end_ts_ns", fields[9]),
            runner_response_write_ts_ns=_parse_runner_optional_ns(
                "response_write_ts_ns",
                fields[10],
            ),
        )
        return Open62541StreamReadResult(
            seq=_parse_runner_int("seq", fields[2]),
            ok=status == "OK",
            value_count=_parse_runner_int("value_count", fields[4]),
            response_timestamp=_datetime_from_unix_ms(fields[5]),
            detail=detail,
            debug_timing=debug_timing,
        )

    def _parse_poll_started_line(self, line: str, *, expected_plan_id: str) -> None:
        """Validate one ``POLL_STARTED`` control line."""

        fields = line.split("\t")
        if len(fields) != 5 or fields[0] != _POLL_STARTED_RESPONSE_PREFIX:
            raise RuntimeError(f"Unexpected poll-start response from runner: {line!r}")
        if fields[1] != expected_plan_id:
            raise RuntimeError(
                "Mismatched plan id in runner poll-start response: "
                f"expected={expected_plan_id!r}, got={fields[1]!r}"
            )

    def _parse_poll_terminal_line(
        self,
        line: str,
        *,
        expected_prefix: str,
        expected_plan_id: str,
    ) -> _PollControlSummary:
        """Parse one ``POLL_DONE`` or ``POLL_STOPPED`` terminal line."""

        fields = line.split("\t")
        if len(fields) != 5 or fields[0] != expected_prefix:
            raise RuntimeError(f"Unexpected polling terminal response from runner: {line!r}")
        if fields[1] != expected_plan_id:
            raise RuntimeError(
                "Mismatched plan id in runner polling terminal response: "
                f"expected={expected_plan_id!r}, got={fields[1]!r}"
            )
        return _PollControlSummary(
            plan_id=fields[1],
            total_ticks=_parse_runner_int("total_ticks", fields[2]),
            ok_count=_parse_runner_int("ok_count", fields[3]),
            error_count=_parse_runner_int("error_count", fields[4]),
        )
