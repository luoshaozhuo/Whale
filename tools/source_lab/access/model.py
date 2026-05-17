"""Tool-side models for source access scanning."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from whale.shared.source.access.model import SourceEndpointSpec, SourcePointSpec


class CapacityMode(str, Enum):
    """Capacity scanning mode."""

    SIMULATOR = "simulator"
    FIELD = "field"


class CapacityStatus(str, Enum):
    """Result status for one capacity level."""

    PASS = "PASS"
    FLAKY = "FLAKY"
    FAIL = "FAIL"
    SKIP = "SKIP"


@dataclass(frozen=True, slots=True)
class PeriodGap:
    """One adjacent response-timestamp period gap."""

    reader_index: int
    gap_index: int
    previous_timestamp_s: float
    current_timestamp_s: float
    period_ms: float


@dataclass(frozen=True, slots=True)
class ResponsePeriodStats:
    """Aggregate response-period metrics from all readers."""

    samples: int
    mean_ms: float
    max_ms: float
    mean_abs_error_ms: float
    worst_gap: PeriodGap | None
    top_gaps: tuple[PeriodGap, ...]


@dataclass(frozen=True, slots=True)
class ServerPreflightResult:
    """Preflight result for one server endpoint."""

    server_name: str
    endpoint: str
    tcp_reachable: bool | None
    protocol_connect_ok: bool
    readable_point_count: int
    expected_point_count: int
    missing_response_timestamp: bool
    status: CapacityStatus
    failure_reason: str = ""


@dataclass(frozen=True, slots=True)
class PreflightResult:
    """Preflight aggregate result for one scan run."""

    by_server: tuple[ServerPreflightResult, ...]

    @property
    def passed(self) -> bool:
        """Return whether all server preflight checks passed."""

        return all(item.status == CapacityStatus.PASS for item in self.by_server)


@dataclass(frozen=True, slots=True)
class CapacityLevelMetrics:
    """Measured metrics for one (server_count, hz) level."""

    server_count: int
    target_hz: float
    target_period_ms: float
    allowed_period_max_ms: float
    allowed_period_mean_abs_error_ms: float
    read_errors: int
    batch_mismatches: int
    missing_response_timestamps: int
    period_samples: int
    period_mean_ms: float
    period_max_ms: float
    period_mean_abs_error_ms: float
    worker_conc_sum: int
    worker_conc_max: int
    worker_conc_by_worker: tuple[int, ...]
    value_count_ok: bool
    period_max_ok: bool
    period_mean_ok: bool
    passed: bool
    failure_reason: str
    worst_gap: PeriodGap | None
    top_gaps: tuple[PeriodGap, ...]


@dataclass(frozen=True, slots=True)
class ConfirmedLevelResult:
    """Final level result after optional fail confirmation retries."""

    primary: CapacityLevelMetrics
    attempts: tuple[CapacityLevelMetrics, ...]
    final_status: CapacityStatus
    final_reason: str


@dataclass(frozen=True, slots=True)
class CapacityScanConfig:
    """Protocol-agnostic capacity scan configuration."""

    mode: CapacityMode
    protocol: str
    endpoints: tuple[SourceEndpointSpec, ...]
    points: tuple[SourcePointSpec, ...]
    server_count_start: int
    server_count_step: int
    server_count_max: int
    hz_start: float
    hz_step: float
    hz_max: float
    process_count: int
    coroutines_per_process: int
    level_duration_s: float = 30.0
    warmup_s: float = 10.0
    read_timeout_s: float = 5.0
    preflight_enabled: bool = True
    preflight_tcp_timeout_s: float = 3.0
    source_update_enabled: bool = False
    source_update_hz: float = 10.0
    max_concurrent_reads: int = 16
    period_max_tolerance_ratio: float = 0.2
    period_mean_error_ratio: float = 0.05
    fail_confirm_runs: int = 2
    accept_flaky_as_pass: bool = False
    stop_hz_ramp_on_first_fail: bool = True
    top_gap_count: int = 10
    fleet_startup_timeout_s: float = 180.0
    fleet_stop_grace_s: float = 0.2
    opcua_client_backend: str = "open62541"
    opcua_simulator_backend: str = "open62541"
    progress_enabled: bool = True
    progress_interval_s: float = 5.0
    port_start: int = 45000
    port_end: int = 65000
    min_expected_point_count: int = 300
    max_expected_point_count: int = 500
    verbose_errors: bool = False
    ignored_profile_scheduler_mode: str | None = None

    def __post_init__(self) -> None:
        if self.server_count_start <= 0 or self.server_count_step <= 0:
            raise ValueError("server_count_start and server_count_step must be greater than 0")
        if self.server_count_max < self.server_count_start:
            raise ValueError("server_count_max must be greater than or equal to server_count_start")
        if self.hz_start <= 0 or self.hz_step <= 0:
            raise ValueError("hz_start and hz_step must be greater than 0")
        if self.hz_max < self.hz_start:
            raise ValueError("hz_max must be greater than or equal to hz_start")
        if self.process_count <= 0:
            raise ValueError("process_count must be greater than 0")
        if self.max_concurrent_reads <= 0:
            raise ValueError("max_concurrent_reads must be greater than 0")
        if self.level_duration_s <= 0 or self.warmup_s < 0 or self.read_timeout_s <= 0:
            raise ValueError("invalid timing config")
        if self.preflight_tcp_timeout_s <= 0:
            raise ValueError("preflight_tcp_timeout_s must be greater than 0")
        if self.progress_interval_s <= 0:
            raise ValueError("progress_interval_s must be greater than 0")

    @classmethod
    def from_env_for_simulator(cls) -> CapacityScanConfig:
        """Build simulator-mode config from environment variables."""

        from .config import from_env_for_simulator

        return from_env_for_simulator()


@dataclass(frozen=True, slots=True)
class CapacityScanResult:
    """Final capacity scan result across all tested levels."""

    config: CapacityScanConfig
    preflight: PreflightResult | None
    levels: tuple[ConfirmedLevelResult, ...]

    @property
    def has_accepted_level(self) -> bool:
        """Return whether at least one level is accepted by config policy."""

        accepted_statuses = {CapacityStatus.PASS}
        if self.config.accept_flaky_as_pass:
            accepted_statuses.add(CapacityStatus.FLAKY)
        return any(level.final_status in accepted_statuses for level in self.levels)
