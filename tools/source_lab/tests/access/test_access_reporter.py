"""Tests for capacity reporter summary semantics."""

from __future__ import annotations

import pytest

from tools.source_lab.access.model import (
    CapacityMode,
    CapacityScanConfig,
    CapacityLevelMetrics,
    CapacityStatus,
    ConfirmedLevelResult,
)
from tools.source_lab.access.reporter import (
    print_level_done,
    print_measurement_progress,
    print_scan_started,
    summarize_server_count_levels,
)


def _config(*, progress_enabled: bool = True) -> CapacityScanConfig:
    return CapacityScanConfig(
        mode=CapacityMode.SIMULATOR,
        protocol="opcua",
        endpoints=(),
        points=(),
        server_count_start=1,
        server_count_step=1,
        server_count_max=2,
        hz_start=10.0,
        hz_step=10.0,
        hz_max=20.0,
        process_count=1,
        coroutines_per_process=0,
        progress_enabled=progress_enabled,
        progress_interval_s=2.0,
    )


def _level(server_count: int, hz: float, status: CapacityStatus) -> ConfirmedLevelResult:
    metrics = CapacityLevelMetrics(
        server_count=server_count,
        target_hz=hz,
        target_period_ms=1000.0 / hz,
        allowed_period_max_ms=1000.0 / hz,
        allowed_period_mean_abs_error_ms=1.0,
        read_errors=0,
        batch_mismatches=0,
        missing_response_timestamps=0,
        period_samples=10,
        period_mean_ms=1000.0 / hz,
        period_max_ms=1000.0 / hz,
        period_mean_abs_error_ms=0.1,
        worker_conc_sum=2,
        worker_conc_max=2,
        worker_conc_by_worker=(2,),
        value_count_ok=True,
        period_max_ok=True,
        period_mean_ok=True,
        passed=status in {CapacityStatus.PASS, CapacityStatus.FLAKY},
        failure_reason="",
        worst_gap=None,
        top_gaps=(),
    )
    return ConfirmedLevelResult(
        primary=metrics,
        attempts=(metrics,),
        final_status=status,
        final_reason="",
    )


def test_summary_distinguishes_stable_flaky_fail() -> None:
    levels = (
        _level(1, 10.0, CapacityStatus.PASS),
        _level(1, 20.0, CapacityStatus.PASS),
        _level(1, 30.0, CapacityStatus.FLAKY),
        _level(1, 40.0, CapacityStatus.FAIL),
    )

    summaries = summarize_server_count_levels(levels, accept_flaky_as_pass=False)

    assert len(summaries) == 1
    summary = summaries[0]
    assert summary.stable_pass_hz == 20.0
    assert summary.first_flaky_hz == 30.0
    assert summary.first_fail_hz == 40.0
    assert summary.best_accepted_hz == 20.0


def test_summary_can_accept_flaky_when_enabled() -> None:
    levels = (
        _level(2, 10.0, CapacityStatus.PASS),
        _level(2, 20.0, CapacityStatus.FLAKY),
    )

    summaries = summarize_server_count_levels(levels, accept_flaky_as_pass=True)

    assert len(summaries) == 1
    assert summaries[0].best_accepted_hz == 20.0


def test_progress_output_contains_key_fields(capsys: pytest.CaptureFixture[str]) -> None:
    """Progress helpers should emit stable key fields."""

    config = _config()
    metrics = _level(1, 10.0, CapacityStatus.PASS).primary

    print_scan_started(config)
    print_measurement_progress(
        config,
        server_count=1,
        target_hz=10.0,
        elapsed_s=2.0,
        ticks=20,
        bad=0,
    )
    print_level_done(
        config,
        metrics=metrics,
        attempt_index=1,
        status=CapacityStatus.PASS,
        reason="",
    )

    output = capsys.readouterr().out
    assert "[source-lab] capacity scan started:" in output
    assert "[source-lab] measurement progress: srv=1 hz=10.0" in output
    assert "elapsed=2.0/30.0s ticks=20 bad=0" in output
    assert "[source-lab] level done: srv=1 hz=10.0 attempt=1 status=PASS" in output


def test_progress_output_can_be_disabled(capsys: pytest.CaptureFixture[str]) -> None:
    """Disabled progress config should suppress progress helpers."""

    config = _config(progress_enabled=False)
    metrics = _level(1, 10.0, CapacityStatus.PASS).primary

    print_scan_started(config)
    print_level_done(
        config,
        metrics=metrics,
        attempt_index=1,
        status=CapacityStatus.PASS,
        reason="",
    )

    assert capsys.readouterr().out == ""
