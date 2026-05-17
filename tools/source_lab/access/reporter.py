"""Reporting helpers for capacity scan results."""

from __future__ import annotations

import os
import time
from dataclasses import dataclass
from typing import Iterable

from .model import CapacityLevelMetrics, CapacityScanConfig, CapacityScanResult, CapacityStatus, ConfirmedLevelResult


def _emit_progress_line(message: str) -> None:
    print(f"[source-lab] {message}", flush=True)


def print_scan_started(config: CapacityScanConfig) -> float:
    """Print scan start progress lines and return start timestamp."""

    started_at = time.perf_counter()
    if not config.progress_enabled:
        return started_at

    _emit_progress_line(
        "capacity scan started: "
        f"mode={config.mode.value} protocol={config.protocol} "
        f"client_backend={config.opcua_client_backend} "
        f"simulator_backend={config.opcua_simulator_backend}"
    )
    _emit_progress_line(
        "scan range: "
        f"servers={config.server_count_start}..{config.server_count_max} step={config.server_count_step}, "
        f"hz={config.hz_start:.1f}..{config.hz_max:.1f} step={config.hz_step:.1f}, "
        f"warmup={config.warmup_s:.1f}s, duration={config.level_duration_s:.1f}s, "
        f"process_count={config.process_count}, "
        f"coroutines_per_process={config.coroutines_per_process}"
    )
    _emit_progress_line(
        f"preflight: enabled={config.preflight_enabled} timeout={config.preflight_tcp_timeout_s:.1f}s"
    )
    return started_at


def print_level_started(
    config: CapacityScanConfig,
    *,
    server_count: int,
    target_hz: float,
    attempt_index: int,
    attempt_total: int,
) -> None:
    """Print one level-attempt start line."""

    if not config.progress_enabled:
        return
    _emit_progress_line(
        "level start: "
        f"srv={server_count} hz={target_hz:.1f} attempt={attempt_index}/{attempt_total} "
        f"period={1000.0 / target_hz:.1f}ms"
    )


def print_preflight_started(config: CapacityScanConfig, *, server_count: int, endpoint_count: int) -> None:
    """Print preflight start progress."""

    if not config.progress_enabled:
        return
    _emit_progress_line(f"preflight start: srv={server_count} endpoints={endpoint_count}")


def print_preflight_finished(
    config: CapacityScanConfig,
    *,
    server_count: int,
    elapsed_s: float,
    passed: bool,
    reason: str = "",
) -> None:
    """Print preflight result progress."""

    if not config.progress_enabled:
        return
    if passed:
        _emit_progress_line(f"preflight ok: srv={server_count} elapsed={elapsed_s:.2f}s")
        return
    _emit_progress_line(f"preflight failed: srv={server_count} reason={reason}")


def print_measurement_started(
    config: CapacityScanConfig,
    *,
    server_count: int,
    target_hz: float,
) -> None:
    """Print measurement start progress."""

    if not config.progress_enabled:
        return
    _emit_progress_line(
        "measurement start: "
        f"srv={server_count} hz={target_hz:.1f} "
        f"warmup={config.warmup_s:.1f}s duration={config.level_duration_s:.1f}s"
    )


def print_measurement_progress(
    config: CapacityScanConfig,
    *,
    server_count: int,
    target_hz: float,
    elapsed_s: float,
    ticks: int,
    bad: int,
    worker_index: int | None = None,
) -> None:
    """Print periodic measurement progress."""

    if not config.progress_enabled:
        return
    worker_suffix = "" if worker_index is None else f" worker={worker_index}"
    _emit_progress_line(
        "measurement progress: "
        f"srv={server_count} hz={target_hz:.1f}{worker_suffix} "
        f"elapsed={elapsed_s:.1f}/{config.level_duration_s:.1f}s ticks={ticks} bad={bad}"
    )


def print_level_done(
    config: CapacityScanConfig,
    *,
    metrics: CapacityLevelMetrics,
    attempt_index: int,
    status: CapacityStatus,
    reason: str,
) -> None:
    """Print one level-attempt completion line."""

    if not config.progress_enabled:
        return
    _emit_progress_line(
        "level done: "
        f"srv={metrics.server_count} hz={metrics.target_hz:.1f} attempt={attempt_index} "
        f"status={status.value} p_max={metrics.period_max_ms:.2f}ms "
        f"mean_err={metrics.period_mean_abs_error_ms:.2f}ms "
        f"bad={metrics.batch_mismatches} reason={reason or '-'}"
    )


def print_stop_hz_ramp(
    config: CapacityScanConfig,
    *,
    server_count: int,
    target_hz: float,
    status: CapacityStatus,
    reason: str,
) -> None:
    """Print stop-ramp progress."""

    if not config.progress_enabled:
        return
    _emit_progress_line(
        f"stop hz ramp: srv={server_count} hz={target_hz:.1f} status={status.value} reason={reason or '-'}"
    )


def print_scan_finished(config: CapacityScanConfig, *, started_at: float) -> None:
    """Print scan finished progress."""

    if not config.progress_enabled:
        return
    elapsed_s = time.perf_counter() - started_at
    _emit_progress_line(f"capacity scan finished: elapsed={elapsed_s:.2f}s")


@dataclass(frozen=True, slots=True)
class ServerCountSummary:
    """Summary values for one server_count ramp."""

    server_count: int
    stable_pass_hz: float | None
    first_flaky_hz: float | None
    first_fail_hz: float | None
    best_accepted_hz: float | None
    best_accepted_p_max_ms: float | None
    best_accepted_mean_err_ms: float | None
    best_accepted_conc_sum: int | None
    best_accepted_failure_reason: str


def summarize_server_count_levels(
    levels: Iterable[ConfirmedLevelResult],
    *,
    accept_flaky_as_pass: bool,
) -> tuple[ServerCountSummary, ...]:
    """Build per-server_count summary for capacity levels."""

    groups: dict[int, list[ConfirmedLevelResult]] = {}
    for level in levels:
        groups.setdefault(level.primary.server_count, []).append(level)

    summaries: list[ServerCountSummary] = []
    for server_count in sorted(groups):
        bucket = sorted(groups[server_count], key=lambda item: item.primary.target_hz)

        stable_pass_hz = next(
            (item.primary.target_hz for item in reversed(bucket) if item.final_status == CapacityStatus.PASS),
            None,
        )
        first_flaky_hz = next(
            (item.primary.target_hz for item in bucket if item.final_status == CapacityStatus.FLAKY),
            None,
        )
        first_fail_hz = next(
            (item.primary.target_hz for item in bucket if item.final_status == CapacityStatus.FAIL),
            None,
        )

        accepted_statuses = {CapacityStatus.PASS}
        if accept_flaky_as_pass:
            accepted_statuses.add(CapacityStatus.FLAKY)

        accepted = [item for item in bucket if item.final_status in accepted_statuses]
        best = accepted[-1].primary if accepted else None

        summaries.append(
            ServerCountSummary(
                server_count=server_count,
                stable_pass_hz=stable_pass_hz,
                first_flaky_hz=first_flaky_hz,
                first_fail_hz=first_fail_hz,
                best_accepted_hz=best.target_hz if best else None,
                best_accepted_p_max_ms=best.period_max_ms if best else None,
                best_accepted_mean_err_ms=best.period_mean_abs_error_ms if best else None,
                best_accepted_conc_sum=best.worker_conc_sum if best else None,
                best_accepted_failure_reason=best.failure_reason if best else "",
            )
        )

    return tuple(summaries)


def print_capacity_report(result: CapacityScanResult) -> None:
    """Print capacity scan detail rows and summary."""

    print()
    print("=" * 132, flush=True)
    print("source_lab capacity scan", flush=True)
    print("=" * 132, flush=True)
    print(f"mode={result.config.mode.value}", flush=True)
    print(f"protocol={result.config.protocol}", flush=True)
    print(
        f"server_count={result.config.server_count_start}:"
        f"{result.config.server_count_step}:{result.config.server_count_max}"
    , flush=True)
    print(f"hz={result.config.hz_start}:{result.config.hz_step}:{result.config.hz_max}", flush=True)
    print(f"preflight_enabled={result.config.preflight_enabled}", flush=True)
    print(f"process_count={result.config.process_count}", flush=True)
    print(f"coroutines_per_process={result.config.coroutines_per_process}", flush=True)
    print(f"max_concurrent_reads={result.config.max_concurrent_reads}", flush=True)
    if result.config.ignored_profile_scheduler_mode:
        print(
            "ignored_env=SOURCE_SIM_PROFILE_SCHEDULER_MODE="
            f"{result.config.ignored_profile_scheduler_mode}"
        , flush=True)
    print("-" * 132, flush=True)
    print(
        f"{'srv':>4} {'hz':>6} {'period':>8} {'bad':>5} {'p_n':>7} {'p_mean':>8} "
        f"{'p_max':>7} {'mean_err':>9} {'conc_sum':>9} {'status':>7} reason"
    , flush=True)
    print("-" * 132, flush=True)

    for level in result.levels:
        metrics = level.primary
        print(
            f"{metrics.server_count:>4} {metrics.target_hz:>6.1f} {metrics.target_period_ms:>8.1f} "
            f"{metrics.batch_mismatches:>5} {metrics.period_samples:>7} {metrics.period_mean_ms:>8.2f} "
            f"{metrics.period_max_ms:>7.2f} {metrics.period_mean_abs_error_ms:>9.2f} "
            f"{metrics.worker_conc_sum:>9} {level.final_status.value:>7} "
            f"{level.final_reason or metrics.failure_reason}"
        , flush=True)
        if level.final_status in {CapacityStatus.FAIL, CapacityStatus.FLAKY} and metrics.top_gaps:
            print("  top response period gaps:", flush=True)
            print("    reader  gap    period_ms    prev_ts             cur_ts", flush=True)
            for gap in metrics.top_gaps:
                print(
                    f"    {gap.reader_index:>6} {gap.gap_index:>4} "
                    f"{gap.period_ms:>12.2f} {gap.previous_timestamp_s:>17.3f} "
                    f"{gap.current_timestamp_s:>17.3f}"
                , flush=True)

    print("-" * 132, flush=True)
    print("summary by server_count:", flush=True)
    summaries = summarize_server_count_levels(
        result.levels,
        accept_flaky_as_pass=result.config.accept_flaky_as_pass,
    )
    for item in summaries:
        print(
            f"  srv={item.server_count}: "
            f"stable_pass_hz={item.stable_pass_hz if item.stable_pass_hz is not None else 'N/A'}, "
            f"first_flaky_hz={item.first_flaky_hz if item.first_flaky_hz is not None else 'N/A'}, "
            f"first_fail_hz={item.first_fail_hz if item.first_fail_hz is not None else 'N/A'}, "
            f"best_accepted_hz={item.best_accepted_hz if item.best_accepted_hz is not None else 'N/A'}, "
            f"p_max={item.best_accepted_p_max_ms if item.best_accepted_p_max_ms is not None else 'N/A'}, "
            f"mean_err={item.best_accepted_mean_err_ms if item.best_accepted_mean_err_ms is not None else 'N/A'}, "
            f"conc_sum={item.best_accepted_conc_sum if item.best_accepted_conc_sum is not None else 'N/A'}, "
            f"failure_reason={item.best_accepted_failure_reason or '-'}"
        , flush=True)
    print("=" * 132, flush=True)
