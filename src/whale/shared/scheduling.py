from __future__ import annotations


def even_stagger_offset(
    *,
    worker_index: int,
    worker_count: int,
    interval_seconds: float,
) -> float:
    """计算一个 polling 周期内的均匀错峰偏移量。"""

    if worker_count <= 0:
        raise ValueError("worker_count must be greater than 0")
    if worker_index < 0 or worker_index >= worker_count:
        raise ValueError("worker_index must be in [0, worker_count)")
    if interval_seconds < 0:
        raise ValueError("interval_seconds must be greater than or equal to 0")

    if worker_count == 1 or interval_seconds == 0:
        return 0.0

    return worker_index * interval_seconds / worker_count
