"""Data models for scenario1 minimal closed loop."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from whale.shared.enums.quality import CleanAction, QualityCode, RunState

ScalarValue = float | int | str | RunState | None

NUMERIC_VALUE_TYPES = {"float", "int"}
SUPPORTED_POINT_CODES = {
    "active_power_kw",
    "wind_speed_ms",
    "rotor_speed_rpm",
    "pitch_angle_deg",
    "generator_bearing_temp_c",
    "run_state",
    "fault_code",
}


@dataclass(frozen=True)
class PointMeta:
    """Point registry metadata derived from the minimal SCL subset.

    Attributes:
        turbine_id: Turbine identifier that owns the point.
        point_code: Stable internal point code used across the pipeline.
        opcua_node_id: OPC UA node id used to resolve incoming measurements.
        value_type: Target scalar type after normalization.
        unit: Engineering unit exposed to downstream stages.
        min_value: Optional lower engineering bound for cleaning.
        max_value: Optional upper engineering bound for cleaning.
        deadband: Optional minimum change threshold before emitting a new value.
        max_rate_of_change: Optional maximum allowed change per second.
        aggregate_group: Optional grouping label used by aggregation logic.
    """

    turbine_id: str
    point_code: str
    opcua_node_id: str
    value_type: str
    unit: str
    min_value: float | None = None
    max_value: float | None = None
    deadband: float | None = None
    max_rate_of_change: float | None = None
    aggregate_group: str | None = None


@dataclass(frozen=True)
class RawBatch:
    """Raw mock OPC UA batch persisted into ODS.

    Attributes:
        batch_id: Stable identifier for the received batch.
        recv_time: Pipeline receive time in UTC.
        turbine_id: Turbine identifier extracted from the payload.
        raw_payload: Source payload retained for traceability and replay.
    """

    batch_id: str
    recv_time: datetime
    turbine_id: str
    raw_payload: dict[str, Any]


@dataclass(frozen=True)
class NormalizedPoint:
    """Normalized measurement mapped onto a stable internal schema.

    Attributes:
        event_time: Measurement event time in UTC.
        ingest_time: Batch receive time carried through the pipeline.
        turbine_id: Turbine identifier for the measurement.
        point_code: Stable internal point code.
        value: Normalized scalar value.
        value_type: Declared target type from registry metadata.
        unit: Engineering unit for the normalized value.
        source_status: Source status string retained from upstream input.
        source_node_id: OPC UA node id that produced the measurement.
    """

    event_time: datetime
    ingest_time: datetime
    turbine_id: str
    point_code: str
    value: ScalarValue
    value_type: str
    unit: str
    source_status: str
    source_node_id: str


@dataclass(frozen=True)
class CleanResult:
    """Cleaning result for a normalized point.

    Attributes:
        normalized_point: The point after any corrective action has been applied.
        quality_code: Final quality assessment assigned by the cleaner.
        clean_action: Action taken by the cleaner.
        clean_reason: Human-readable reason for the chosen action.
    """

    normalized_point: NormalizedPoint
    quality_code: QualityCode
    clean_action: CleanAction
    clean_reason: str


@dataclass(frozen=True)
class DwdRecord:
    """Cleaned detail record written into DWD.

    Attributes:
        ts: Event timestamp in UTC.
        ingest_time: Upstream ingest timestamp in UTC.
        turbine_id: Turbine identifier.
        point_code: Stable internal point code.
        value: Cleaned scalar value stored in DWD.
        quality_code: Final quality code after cleaning.
    """

    ts: datetime
    ingest_time: datetime
    turbine_id: str
    point_code: str
    value: ScalarValue
    quality_code: QualityCode


@dataclass(frozen=True)
class DwsRealtimeAggregate:
    """Realtime DWS aggregate over a 5-second sliding window.

    Attributes:
        window_end_time: Inclusive UTC timestamp for the window end.
        turbine_id: Turbine identifier.
        avg_active_power_kw: Average active power over the window.
        avg_wind_speed_ms: Average wind speed over the window.
        max_generator_bearing_temp_c: Maximum generator bearing temperature.
        run_state_last: Last observed run state in the window.
        bad_quality_ratio: Share of BAD or SUSPECT records in the window.
    """

    window_end_time: datetime
    turbine_id: str
    avg_active_power_kw: float | None
    avg_wind_speed_ms: float | None
    max_generator_bearing_temp_c: float | None
    run_state_last: RunState
    bad_quality_ratio: float


@dataclass(frozen=True)
class DwsPeriodicAggregate:
    """Periodic DWS aggregate over a 1-minute bucket.

    Attributes:
        bucket_time: Minute bucket start time in UTC.
        turbine_id: Turbine identifier.
        energy_increment_kwh: Estimated energy increment for the bucket.
        avg_active_power_kw: Average active power for the bucket.
        avg_pitch_angle_deg: Average pitch angle for the bucket.
    """

    bucket_time: datetime
    turbine_id: str
    energy_increment_kwh: float
    avg_active_power_kw: float | None
    avg_pitch_angle_deg: float | None


@dataclass(frozen=True)
class AdsPowerCurveDeviation:
    """ADS power-curve deviation result.

    Attributes:
        bucket_time: Minute bucket start time in UTC.
        turbine_id: Turbine identifier.
        wind_speed_bin: Rounded wind-speed bin matched against the power curve.
        actual_power_kw: Observed average active power.
        theoretical_power_kw: Expected power from the theoretical curve.
        deviation_kw: Difference between actual and theoretical power.
    """

    bucket_time: datetime
    turbine_id: str
    wind_speed_bin: float
    actual_power_kw: float
    theoretical_power_kw: float
    deviation_kw: float


@dataclass(frozen=True)
class AdsAvailability:
    """ADS turbine availability result.

    Attributes:
        bucket_time: Minute bucket start time in UTC.
        turbine_id: Turbine identifier.
        availability_ratio: Ratio of estimated running time to full minute length.
        run_time_sec: Estimated running seconds inside the bucket.
        bad_quality_ratio: Share of BAD or SUSPECT run-state records.
    """

    bucket_time: datetime
    turbine_id: str
    availability_ratio: float
    run_time_sec: float
    bad_quality_ratio: float


@dataclass(frozen=True)
class PipelineRunResult:
    """Collected output from a scenario1 pipeline run.

    Attributes:
        raw_batches_written: Number of raw batches stored in ODS.
        keyframes_written: Number of keyframes stored in ODS.
        dwd_records_written: Number of DWD records written during cleaning.
        realtime_results: Realtime DWS aggregation output.
        periodic_results: Periodic DWS aggregation output.
        power_curve_results: ADS power-curve deviation output.
        availability_results: ADS availability output.
    """

    raw_batches_written: int
    keyframes_written: int
    dwd_records_written: int
    realtime_results: list[DwsRealtimeAggregate] = field(default_factory=list)
    periodic_results: list[DwsPeriodicAggregate] = field(default_factory=list)
    power_curve_results: list[AdsPowerCurveDeviation] = field(default_factory=list)
    availability_results: list[AdsAvailability] = field(default_factory=list)
