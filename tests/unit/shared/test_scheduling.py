from __future__ import annotations

import pytest

from whale.shared.scheduling import even_stagger_offset


def test_even_stagger_offset_returns_zero_for_single_worker() -> None:
    assert even_stagger_offset(
        worker_index=0,
        worker_count=1,
        interval_seconds=0.1,
    ) == 0.0


def test_even_stagger_offset_returns_zero_for_zero_interval() -> None:
    assert even_stagger_offset(
        worker_index=0,
        worker_count=4,
        interval_seconds=0.0,
    ) == 0.0


@pytest.mark.parametrize(
    ("worker_index", "expected_offset"),
    [
        (0, 0.0),
        (1, 0.025),
        (2, 0.05),
        (3, 0.075),
    ],
)
def test_even_stagger_offset_spreads_workers_evenly(
    worker_index: int,
    expected_offset: float,
) -> None:
    assert even_stagger_offset(
        worker_index=worker_index,
        worker_count=4,
        interval_seconds=0.1,
    ) == pytest.approx(expected_offset)


@pytest.mark.parametrize("worker_count", [0, -1])
def test_even_stagger_offset_rejects_non_positive_worker_count(worker_count: int) -> None:
    with pytest.raises(ValueError, match="worker_count"):
        even_stagger_offset(
            worker_index=0,
            worker_count=worker_count,
            interval_seconds=0.1,
        )


def test_even_stagger_offset_rejects_negative_worker_index() -> None:
    with pytest.raises(ValueError, match="worker_index"):
        even_stagger_offset(
            worker_index=-1,
            worker_count=4,
            interval_seconds=0.1,
        )


def test_even_stagger_offset_rejects_worker_index_at_or_above_worker_count() -> None:
    with pytest.raises(ValueError, match="worker_index"):
        even_stagger_offset(
            worker_index=4,
            worker_count=4,
            interval_seconds=0.1,
        )


def test_even_stagger_offset_rejects_negative_interval() -> None:
    with pytest.raises(ValueError, match="interval_seconds"):
        even_stagger_offset(
            worker_index=0,
            worker_count=4,
            interval_seconds=-0.1,
        )
