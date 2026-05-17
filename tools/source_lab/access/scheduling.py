# mypy: disable-error-code=import-untyped
"""Scheduling helpers for capacity scan orchestration."""

from __future__ import annotations

import multiprocessing as mp
from collections.abc import Iterator, Sequence
from dataclasses import dataclass

from whale.shared.source.scheduling import build_even_stagger_offsets
from tools.source_lab.access.providers.base import SourceRuntimeSpec


@dataclass(frozen=True, slots=True)
class SourceReadSpec:
    """One source plus globally assigned stagger offset."""

    global_index: int
    source: SourceRuntimeSpec
    offset_seconds: float


def iter_int_ramp(start: int, step: int, maximum: int) -> Iterator[int]:
    """Yield integer ramp values from start to maximum, inclusive."""

    current = start
    while current <= maximum:
        yield current
        current += step


def iter_float_ramp(start: float, step: float, maximum: float) -> Iterator[float]:
    """Yield float ramp values from start to maximum with numeric tolerance."""

    current = start
    while current <= maximum + 1e-12:
        yield round(current, 10)
        current += step


def build_source_specs(
    sources: Sequence[SourceRuntimeSpec],
    *,
    target_hz: float,
) -> tuple[SourceReadSpec, ...]:
    """Build globally staggered read specs for one level."""

    offsets = build_even_stagger_offsets(count=len(sources), interval_seconds=1.0 / target_hz)
    return tuple(
        SourceReadSpec(global_index=index, source=source, offset_seconds=offsets[index])
        for index, source in enumerate(sources)
    )


def partition_specs_round_robin(
    specs: Sequence[SourceReadSpec],
    *,
    process_count: int,
) -> tuple[tuple[SourceReadSpec, ...], ...]:
    """Partition source specs with round-robin distribution across workers."""

    buckets: list[list[SourceReadSpec]] = [[] for _ in range(process_count)]
    for index, spec in enumerate(specs):
        buckets[index % process_count].append(spec)
    return tuple(tuple(bucket) for bucket in buckets)


def resolve_mp_context() -> mp.context.BaseContext:
    """Resolve multiprocessing context, preferring fork when available."""

    methods = mp.get_all_start_methods()
    if "fork" in methods:
        return mp.get_context("fork")
    return mp.get_context()
