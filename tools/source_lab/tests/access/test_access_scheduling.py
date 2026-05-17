"""Tests for access scheduling helpers."""

from __future__ import annotations

from whale.shared.source.access.model import SourceEndpointSpec, SourcePointSpec
from tools.source_lab.access.providers.base import SourceRuntimeSpec
from tools.source_lab.access.scheduling import (
    build_source_specs,
    iter_float_ramp,
    iter_int_ramp,
    partition_specs_round_robin,
)


def _runtime_spec(index: int) -> SourceRuntimeSpec:
    endpoint = SourceEndpointSpec(
        name=f"s{index}",
        host="127.0.0.1",
        port=48000 + index,
        protocol="opcua",
    )
    points = (SourcePointSpec(address="IED.LD.LN.DO"),)
    return SourceRuntimeSpec(endpoint=endpoint, points=points)


def test_iter_int_ramp() -> None:
    assert tuple(iter_int_ramp(1, 4, 10)) == (1, 5, 9)


def test_iter_float_ramp() -> None:
    assert tuple(iter_float_ramp(5.0, 5.0, 15.0)) == (5.0, 10.0, 15.0)


def test_partition_specs_round_robin() -> None:
    specs = tuple(build_source_specs(tuple(_runtime_spec(i) for i in range(5)), target_hz=10.0))
    buckets = partition_specs_round_robin(specs, process_count=2)

    assert len(buckets) == 2
    assert len(buckets[0]) == 3
    assert len(buckets[1]) == 2


def test_build_source_specs_offset_range() -> None:
    target_hz = 10.0
    interval_seconds = 1.0 / target_hz
    specs = build_source_specs(tuple(_runtime_spec(i) for i in range(4)), target_hz=target_hz)

    assert len(specs) == 4
    for spec in specs:
        assert 0.0 <= spec.offset_seconds < interval_seconds
