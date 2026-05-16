"""Shared metric helpers for source simulation tests."""

from __future__ import annotations

import statistics
from collections.abc import Sequence
from dataclasses import dataclass


def percentile(sorted_values: Sequence[float], pct: float) -> float:
    """Compute percentile from pre-sorted values via linear interpolation."""
    if not sorted_values:
        return 0.0

    if len(sorted_values) == 1:
        return sorted_values[0]

    index = (pct / 100.0) * (len(sorted_values) - 1)
    low = int(index)
    high = min(low + 1, len(sorted_values) - 1)
    fraction = index - low

    return sorted_values[low] + fraction * (sorted_values[high] - sorted_values[low])


def safe_mean(values: Sequence[float]) -> float:
    """Return mean or 0.0 for empty input."""
    return statistics.mean(values) if values else 0.0


def safe_max(values: Sequence[float]) -> float:
    """Return max or 0.0 for empty input."""
    return max(values, default=0.0)


def safe_percentile(values: Sequence[float], pct: float) -> float:
    """Return percentile or 0.0 for empty input."""
    return percentile(sorted(values), pct) if values else 0.0


@dataclass(frozen=True, slots=True)
class PeriodStats:
    """Period stability metrics across one or multiple readers."""

    samples: int
    pass_ratio: float
    min_reader_pass_ratio: float
    jitter_p95_ms: float
    jitter_p99_ms: float
    jitter_max_ms: float


def evaluate_period_by_reader(
    timestamps_by_reader: Sequence[Sequence[float]],
    *,
    target_hz: float,
    tolerance_ratio: float,
) -> PeriodStats:
    """Evaluate period pass ratio and jitter from timestamp series."""
    if target_hz <= 0:
        return PeriodStats(0, 0.0, 0.0, 0.0, 0.0, 0.0)

    target_period_s = 1.0 / target_hz
    allowed_error_s = target_period_s * tolerance_ratio

    all_errors_ms: list[float] = []
    all_pass_count = 0
    all_sample_count = 0
    reader_pass_ratios: list[float] = []

    for timestamps in timestamps_by_reader:
        if len(timestamps) < 2:
            continue

        reader_sample_count = 0
        reader_pass_count = 0

        for index in range(1, len(timestamps)):
            gap_s = timestamps[index] - timestamps[index - 1]
            if gap_s <= 0:
                continue

            error_s = abs(gap_s - target_period_s)
            all_errors_ms.append(error_s * 1000.0)
            reader_sample_count += 1
            all_sample_count += 1

            if error_s <= allowed_error_s:
                reader_pass_count += 1
                all_pass_count += 1

        if reader_sample_count > 0:
            reader_pass_ratios.append(reader_pass_count / reader_sample_count)

    if all_sample_count <= 0:
        return PeriodStats(0, 0.0, 0.0, 0.0, 0.0, 0.0)

    return PeriodStats(
        samples=all_sample_count,
        pass_ratio=all_pass_count / all_sample_count,
        min_reader_pass_ratio=min(reader_pass_ratios, default=0.0),
        jitter_p95_ms=round(safe_percentile(all_errors_ms, 95), 1),
        jitter_p99_ms=round(safe_percentile(all_errors_ms, 99), 1),
        jitter_max_ms=round(safe_max(all_errors_ms), 1),
    )
