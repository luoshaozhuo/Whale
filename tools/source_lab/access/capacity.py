# mypy: disable-error-code=import-untyped
"""Protocol-agnostic source capacity scanner orchestration."""

from __future__ import annotations

from collections.abc import Sequence
import time

from tools.source_lab.access.metrics import build_skip_result
from tools.source_lab.access.model import (
    CapacityLevelMetrics,
    CapacityScanConfig,
    CapacityScanResult,
    CapacityStatus,
    ConfirmedLevelResult,
    PreflightResult,
)
from tools.source_lab.access.preflight import run_preflight
from tools.source_lab.access.providers.base import SourceProvider, SourceRuntimeSpec
from tools.source_lab.access.reporter import (
    print_level_done,
    print_level_started,
    print_measurement_started,
    print_preflight_finished,
    print_preflight_started,
    print_scan_finished,
    print_scan_started,
    print_stop_hz_ramp,
)
from tools.source_lab.access.scheduling import iter_float_ramp, iter_int_ramp
from tools.source_lab.access.worker import run_level_once


def _run_confirmed_level(
    sources: Sequence[SourceRuntimeSpec],
    *,
    target_hz: float,
    config: CapacityScanConfig,
) -> ConfirmedLevelResult:
    if (
        config.coroutines_per_process > 0
        and len(sources) > config.process_count * config.coroutines_per_process
    ):
        result = build_skip_result(
            server_count=len(sources),
            target_hz=target_hz,
            reason="server_count exceeds process_count * coroutines_per_process",
            config=config,
        )
        print_level_done(
            config,
            metrics=result.primary,
            attempt_index=1,
            status=result.final_status,
            reason=result.final_reason,
        )
        return result

    attempts: list[CapacityLevelMetrics] = []
    max_attempts = max(1, config.fail_confirm_runs)
    for attempt_index in range(1, max_attempts + 1):
        print_level_started(
            config,
            server_count=len(sources),
            target_hz=target_hz,
            attempt_index=attempt_index,
            attempt_total=max_attempts,
        )
        print_measurement_started(config, server_count=len(sources), target_hz=target_hz)
        metrics = run_level_once(sources, target_hz=target_hz, config=config)
        attempts.append(metrics)
        if metrics.passed:
            if len(attempts) == 1:
                result = ConfirmedLevelResult(
                    primary=attempts[0],
                    attempts=tuple(attempts),
                    final_status=CapacityStatus.PASS,
                    final_reason="",
                )
                print_level_done(
                    config,
                    metrics=metrics,
                    attempt_index=attempt_index,
                    status=result.final_status,
                    reason=result.final_reason,
                )
                return result
            result = ConfirmedLevelResult(
                primary=attempts[0],
                attempts=tuple(attempts),
                final_status=CapacityStatus.FLAKY,
                final_reason=f"recovered on attempt {len(attempts)}",
            )
            print_level_done(
                config,
                metrics=metrics,
                attempt_index=attempt_index,
                status=result.final_status,
                reason=result.final_reason,
            )
            return result

        print_level_done(
            config,
            metrics=metrics,
            attempt_index=attempt_index,
            status=CapacityStatus.FAIL,
            reason=metrics.failure_reason,
        )

    result = ConfirmedLevelResult(
        primary=attempts[0],
        attempts=tuple(attempts),
        final_status=CapacityStatus.FAIL,
        final_reason=attempts[-1].failure_reason,
    )
    return result


def scan_source_capacity(
    config: CapacityScanConfig,
    *,
    provider: SourceProvider,
) -> CapacityScanResult:
    """Run capacity scan across server_count and hz ramps."""

    started_at = print_scan_started(config)
    level_results: list[ConfirmedLevelResult] = []
    preflight_rows: list = []
    preflight_enabled = getattr(config, "preflight_enabled", True)

    try:
        for server_count in iter_int_ramp(
            config.server_count_start,
            config.server_count_step,
            config.server_count_max,
        ):
            sources = provider.build_sources(config, server_count=server_count)
            with provider.started(sources):
                if preflight_enabled:
                    print_preflight_started(
                        config,
                        server_count=server_count,
                        endpoint_count=len(sources),
                    )
                    preflight_started_at = time.perf_counter()
                    preflight = run_preflight(config, sources)
                    preflight_elapsed_s = time.perf_counter() - preflight_started_at
                    preflight_rows.extend(preflight.by_server)
                    if not preflight.passed:
                        reason = "; ".join(
                            f"{item.server_name}:{item.failure_reason}"
                            for item in preflight.by_server
                            if item.status != CapacityStatus.PASS
                        )
                        print_preflight_finished(
                            config,
                            server_count=server_count,
                            elapsed_s=preflight_elapsed_s,
                            passed=False,
                            reason=reason,
                        )
                        level_results.append(
                            build_skip_result(
                                server_count=server_count,
                                target_hz=config.hz_start,
                                reason=f"preflight_failed: {reason}",
                                config=config,
                            )
                        )
                        continue
                    print_preflight_finished(
                        config,
                        server_count=server_count,
                        elapsed_s=preflight_elapsed_s,
                        passed=True,
                    )

                for target_hz in iter_float_ramp(config.hz_start, config.hz_step, config.hz_max):
                    result = _run_confirmed_level(sources, target_hz=target_hz, config=config)
                    level_results.append(result)
                    if (
                        config.stop_hz_ramp_on_first_fail
                        and result.final_status
                        in {
                            CapacityStatus.FLAKY,
                            CapacityStatus.FAIL,
                            CapacityStatus.SKIP,
                        }
                    ):
                        print_stop_hz_ramp(
                            config,
                            server_count=server_count,
                            target_hz=target_hz,
                            status=result.final_status,
                            reason=result.final_reason or result.primary.failure_reason,
                        )
                        break
    finally:
        print_scan_finished(config, started_at=started_at)

    preflight_result = PreflightResult(by_server=tuple(preflight_rows)) if preflight_enabled else None
    return CapacityScanResult(
        config=config,
        preflight=preflight_result,
        levels=tuple(level_results),
    )
