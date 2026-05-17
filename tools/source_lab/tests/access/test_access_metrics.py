"""Tests for access metrics helpers."""

from __future__ import annotations

import pytest

from tools.source_lab.access.metrics import (
    WorkerRawStats,
    build_level_metrics,
    build_skip_result,
    evaluate_response_periods,
)
from tools.source_lab.access.model import CapacityMode, CapacityScanConfig, CapacityStatus


def _config() -> CapacityScanConfig:
    return CapacityScanConfig(
        mode=CapacityMode.SIMULATOR,
        protocol="opcua",
        endpoints=(),
        points=(),
        server_count_start=1,
        server_count_step=1,
        server_count_max=1,
        hz_start=10.0,
        hz_step=10.0,
        hz_max=10.0,
        process_count=1,
        coroutines_per_process=0,
        period_max_tolerance_ratio=0.2,
        period_mean_error_ratio=0.05,
    )


def test_evaluate_response_periods_basic() -> None:
    stats = evaluate_response_periods(
        ((1.0, 1.1, 1.2),),
        target_period_ms=100.0,
        top_n=3,
    )

    assert stats.samples == 2
    assert stats.mean_ms == pytest.approx(100.0)
    assert stats.max_ms == pytest.approx(100.0)


def test_build_skip_result_status() -> None:
    result = build_skip_result(
        server_count=1,
        target_hz=10.0,
        reason="skip_reason",
        config=_config(),
    )

    assert result.final_status == CapacityStatus.SKIP
    assert result.final_reason == "skip_reason"


def test_build_level_metrics_contains_pmax_reason() -> None:
    config = _config()
    worker_stats = (
        WorkerRawStats(
            worker_index=0,
            reader_count=1,
            batch_mismatches=0,
            read_errors=0,
            missing_response_timestamps=0,
            response_timestamps_by_reader=((1.0, 1.25),),
            max_observed_concurrent_reads=1,
        ),
    )

    metrics = build_level_metrics(
        worker_stats,
        server_count=1,
        target_hz=10.0,
        config=config,
    )

    assert metrics.period_max_ok is False
    assert "pmax=" in metrics.failure_reason
