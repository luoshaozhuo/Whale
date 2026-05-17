"""open62541-based OPC UA source simulator backend.

Python 侧负责：
1. 生成 runner TSV 配置；
2. 启动 open62541 C runner；
3. 等待 TCP endpoint 可连接；
4. 通过 stdin 向 runner 下发写入命令；
5. stop 时 terminate / kill；
6. 清理临时目录。
"""

from __future__ import annotations

import os
import socket
import subprocess
import tempfile
import time
from collections import OrderedDict
from pathlib import Path

from tools.source_lab.opcua.address_space import (
    build_address_space,
    opcua_data_type,
    render_open62541_tsv,
)
from tools.source_lab.model import SimulatedPoint, SimulatedSource


_STARTUP_TIMEOUT_SECONDS = 10.0
_READY_POLL_SECONDS = 0.05
_STOP_TIMEOUT_SECONDS = 5.0


class Open62541SourceSimulatorError(RuntimeError):
    """Raised when open62541 simulator fails to start or stop cleanly."""


class Open62541SourceSimulator:
    """OPC UA simulator backend implemented by an external open62541 C runner."""

    def __init__(self, source: SimulatedSource, *, startup_timeout_seconds: float = 10.0) -> None:
        normalized_protocol = (
            source.connection.protocol.strip().lower().replace("_", "").replace("-", "")
        )
        if normalized_protocol != "opcua":
            raise Open62541SourceSimulatorError(
                "Open62541SourceSimulator only supports `opcua` sources"
            )

        timeout_from_params = source.connection.params.get("open62541_startup_timeout_seconds")
        resolved_startup_timeout = startup_timeout_seconds
        if isinstance(timeout_from_params, (int, float)) and float(timeout_from_params) > 0:
            resolved_startup_timeout = float(timeout_from_params)
        if resolved_startup_timeout <= 0:
            resolved_startup_timeout = _STARTUP_TIMEOUT_SECONDS

        self._source = source
        self._startup_timeout_seconds = resolved_startup_timeout
        self._address_space = build_address_space(source)
        self._temp_dir: tempfile.TemporaryDirectory[str] | None = None
        self._config_path: Path | None = None
        self._process: subprocess.Popen[str] | None = None
        self._write_targets_by_key: dict[str, tuple[str, SimulatedPoint]] = {}

    @property
    def endpoint(self) -> str:
        """Return OPC UA server endpoint."""
        return self._address_space.endpoint

    @property
    def name(self) -> str:
        """Return simulator source name."""
        return self._source.connection.name

    def start(self) -> "Open62541SourceSimulator":
        """Start open62541 runner process.

        Returns:
            Self.

        Raises:
            Open62541SourceSimulatorError: If runner is missing or startup fails.
        """
        if self._process is not None:
            return self

        runner_path = resolve_runner_path()
        if not runner_path.exists():
            raise Open62541SourceSimulatorError(
                "open62541 runner executable does not exist: "
                f"{runner_path}. Build it first with CMake."
            )

        self._config_path = self._build_config_file()
        config_path = self._config_path

        self._process = subprocess.Popen(
            [str(runner_path), str(config_path)],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            bufsize=1,
        )

        try:
            self._wait_until_ready()
        except Exception:
            stdout, stderr = self._terminate_and_collect_output()
            self._cleanup_temp_dir()
            self._process = None
            raise Open62541SourceSimulatorError(
                "Failed to start open62541 simulator runner.\n"
                f"endpoint={self.endpoint}\n"
                f"config_path={config_path}\n"
                f"stdout:\n{stdout}\n"
                f"stderr:\n{stderr}"
            ) from None

        self._write_targets_by_key = {}
        points_by_key = {point.key: point for point in self._source.points}
        for variable in self._address_space.variables:
            point = points_by_key.get(variable.point_key)
            if point is None:
                continue

            target = (variable.node_id, point)
            self._write_targets_by_key[variable.point_key] = target
            self._write_targets_by_key[variable.node_id] = target

        return self

    def stop(self) -> None:
        """Stop open62541 runner process and clean temporary files."""
        if self._process is None:
            self._cleanup_temp_dir()
            return

        process = self._process
        if process.poll() is None:
            process.terminate()

            try:
                process.communicate(timeout=_STOP_TIMEOUT_SECONDS)
            except subprocess.TimeoutExpired:
                process.kill()
                process.communicate(timeout=_STOP_TIMEOUT_SECONDS)

        self._process = None
        self._write_targets_by_key = {}
        self._cleanup_temp_dir()

    def __enter__(self) -> "Open62541SourceSimulator":
        return self.start()

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        self.stop()

    def writes(self, values_by_key: dict[str, str | int | float | bool]) -> None:
        """Write simulated point values through the open62541 runner stdin.

        Args:
            values_by_key: Mapping from point key or full logical path to value.

        Raises:
            RuntimeError: If simulator is not started or runner stdin is unavailable.
        """
        if self._process is None or self._process.poll() is not None:
            raise RuntimeError("Simulator runtime must be started before writes()")

        # If SOURCE_SIM_LOAD_SOURCE_UPDATE_ENABLED is true, the runner handles all updates
        # internally. Don't send writes through stdin to avoid double-update overhead.
        load_update_enabled = os.environ.get("SOURCE_SIM_LOAD_SOURCE_UPDATE_ENABLED", "false")
        if load_update_enabled.strip().lower() in {"1", "true", "yes", "on"}:
            return

        if self._process.stdin is None:
            raise RuntimeError("Open62541 runner stdin is unavailable for writes()")

        commands: list[str] = []

        for key, value in values_by_key.items():
            target = self._write_targets_by_key.get(key)
            if target is None:
                continue

            node_id, point = target
            serialized = self._serialize_value(point, value)
            commands.append(
                "\t".join(
                    (
                        "write",
                        self._validate_command_field(node_id),
                        self._validate_command_field(opcua_data_type(point.data_type)),
                        serialized,
                    )
                )
                + "\n"
            )

        if not commands:
            return

        try:
            self._process.stdin.write("".join(commands))
            self._process.stdin.flush()
        except BrokenPipeError as exc:
            raise RuntimeError("Open62541 runner stdin pipe is broken") from exc
        except OSError as exc:
            raise RuntimeError("Failed to write command to open62541 runner") from exc

    def _build_config_file(self) -> Path:
        """Build temporary TSV config file for open62541 runner."""
        self._temp_dir = tempfile.TemporaryDirectory(prefix="open62541_source_sim_")
        config_path = Path(self._temp_dir.name) / f"{self.name}.tsv"
        config_path.write_text(
            render_open62541_tsv(
                self._address_space,
                extra_records=self._runner_config_records(),
            ),
            encoding="utf-8",
        )
        return config_path

    def _runner_config_records(self) -> dict[str, str]:
        """Build extra runner configuration records for the TSV file."""
        load_update_enabled = os.environ.get("SOURCE_SIM_LOAD_SOURCE_UPDATE_ENABLED", "false")
        update_enabled = load_update_enabled.strip().lower() in {"1", "true", "yes", "on"}
        update_interval_ms = _resolve_internal_update_interval_ms()
        return OrderedDict(
            (
                ("update_enabled", "true" if update_enabled else "false"),
                ("update_interval_ms", str(update_interval_ms)),
                ("update_all", "true"),
            )
        )

    def _wait_until_ready(self) -> None:
        """Wait until runner TCP endpoint is connectable."""
        if self._process is None:
            raise Open62541SourceSimulatorError("Runner process has not been started")

        host = self._source.connection.host
        port = int(self._source.connection.port)
        deadline = time.monotonic() + self._startup_timeout_seconds

        while time.monotonic() < deadline:
            if self._process.poll() is not None:
                raise Open62541SourceSimulatorError(
                    f"Runner exited before ready: exitcode={self._process.returncode}"
                )

            if _can_connect(host, port):
                return

            time.sleep(_READY_POLL_SECONDS)

        raise Open62541SourceSimulatorError(
            f"Timed out waiting for open62541 endpoint: {host}:{port}"
        )

    def _terminate_and_collect_output(self) -> tuple[str, str]:
        """Terminate failed runner and collect stdout/stderr."""
        if self._process is None:
            return "", ""

        process = self._process
        if process.poll() is None:
            process.terminate()

        try:
            stdout, stderr = process.communicate(timeout=_STOP_TIMEOUT_SECONDS)
        except subprocess.TimeoutExpired:
            process.kill()
            stdout, stderr = process.communicate(timeout=_STOP_TIMEOUT_SECONDS)

        return stdout or "", stderr or ""

    def _cleanup_temp_dir(self) -> None:
        """Clean temporary config directory."""
        if self._temp_dir is not None:
            self._temp_dir.cleanup()
            self._temp_dir = None
            self._config_path = None

    def _serialize_value(
        self,
        point: SimulatedPoint,
        value: str | int | float | bool | None,
    ) -> str:
        """Serialize external value into the scalar text format expected by the runner."""
        opcua_type_name = opcua_data_type(point.data_type)

        if opcua_type_name == "Boolean":
            if isinstance(value, str):
                return self._validate_command_field(
                    "true" if value.strip().lower() in {"1", "true", "yes", "on"} else "false"
                )
            return self._validate_command_field("true" if bool(value) else "false")

        if opcua_type_name == "Int32":
            casted = int(float(value or 0))
            return self._validate_command_field(
                str(max(-2147483648, min(2147483647, casted)))
            )

        if opcua_type_name == "String":
            return self._validate_command_field(str(value or ""))

        return self._validate_command_field(str(float(value or 0.0)))

    def _validate_command_field(self, value: str) -> str:
        """Validate one stdin command field."""
        if "\t" in value or "\n" in value or "\r" in value:
            raise ValueError(
                f"Open62541 write value contains unsupported control character: {value!r}"
            )
        return value


def resolve_runner_path() -> Path:
    """Resolve open62541 source simulator executable path.

    Environment override:
        SOURCE_SIM_OPEN62541_RUNNER_PATH

    Returns:
        Runner executable path.
    """
    env_path = os.environ.get("SOURCE_SIM_OPEN62541_RUNNER_PATH")
    if env_path:
        return Path(env_path).expanduser().resolve()

    source_lab_root = Path(__file__).resolve().parents[1]
    runner_name = "open62541_source_simulator.exe" if os.name == "nt" else "open62541_source_simulator"
    return source_lab_root / "native" / "build" / runner_name


def _can_connect(host: str, port: int) -> bool:
    """Check whether TCP endpoint accepts connections."""
    try:
        with socket.create_connection((host, port), timeout=0.2):
            return True
    except OSError:
        return False


def _resolve_internal_update_interval_ms() -> int:
    """Resolve internal update interval from SOURCE_SIM_LOAD_SOURCE_UPDATE_HZ."""
    raw_hz = os.environ.get("SOURCE_SIM_LOAD_SOURCE_UPDATE_HZ", "10")

    try:
        hz = float(raw_hz)
    except ValueError:
        hz = 10.0

    if hz <= 0:
        return 1000

    return max(1, round(1000.0 / hz))