"""Aggregation helpers for DWS and ADS outputs."""

from whale.aggregation.ads import (
    aggregate_availability,
    aggregate_power_curve_deviation,
    load_power_curve,
)
from whale.aggregation.periodic import aggregate_periodic
from whale.aggregation.realtime import aggregate_realtime

__all__ = [
    "aggregate_availability",
    "aggregate_periodic",
    "aggregate_power_curve_deviation",
    "aggregate_realtime",
    "load_power_curve",
]
