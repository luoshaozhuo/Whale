"""Shared CPU sampling helpers for load tests."""

from __future__ import annotations

import asyncio
import multiprocessing
import time
from collections.abc import Sequence


def read_cpu_stat() -> tuple[int, int]:
    """Read /proc/stat and return total and idle tick counters."""
    with open("/proc/stat", "r", encoding="utf-8") as fp:
        parts = fp.readline().split()

    if len(parts) < 8 or parts[0] != "cpu":
        raise RuntimeError("Unexpected /proc/stat format")

    values = [int(item) for item in parts[1:]]
    idle = values[3] + values[4]
    total = sum(values)
    return total, idle


async def sample_cpu_percent_async(
    stop_event: asyncio.Event,
    *,
    interval_s: float = 0.25,
) -> list[float]:
    """Sample total CPU usage periodically until stop_event is set."""
    try:
        prev_total, prev_idle = read_cpu_stat()
    except Exception:
        return []

    samples: list[float] = []

    while not stop_event.is_set():
        await asyncio.sleep(interval_s)

        try:
            cur_total, cur_idle = read_cpu_stat()
        except Exception:
            break

        delta_total = cur_total - prev_total
        delta_idle = cur_idle - prev_idle
        prev_total, prev_idle = cur_total, cur_idle

        if delta_total <= 0:
            continue

        used_ratio = max(0.0, min(1.0, (delta_total - delta_idle) / delta_total))
        samples.append(used_ratio * 100.0)

    return samples


def sample_cpu_percent_blocking_until(
    processes: Sequence[multiprocessing.Process],
    *,
    interval_s: float = 0.25,
    timeout_s: float | None = None,
) -> list[float]:
    """Sample total CPU usage while any worker process is alive.

    Args:
        processes: Worker processes to observe.
        interval_s: Sampling interval in seconds.
        timeout_s: Optional wall-clock budget. When provided, sampling stops
            after this many seconds even if some processes are still alive.
    """
    try:
        prev_total, prev_idle = read_cpu_stat()
    except Exception:
        return []

    samples: list[float] = []
    deadline = time.monotonic() + timeout_s if timeout_s is not None else None

    while any(process.is_alive() for process in processes):
        if deadline is not None and time.monotonic() >= deadline:
            break
        time.sleep(interval_s)

        try:
            cur_total, cur_idle = read_cpu_stat()
        except Exception:
            break

        delta_total = cur_total - prev_total
        delta_idle = cur_idle - prev_idle
        prev_total, prev_idle = cur_total, cur_idle

        if delta_total <= 0:
            continue

        used_ratio = max(0.0, min(1.0, (delta_total - delta_idle) / delta_total))
        samples.append(used_ratio * 100.0)

    return samples
