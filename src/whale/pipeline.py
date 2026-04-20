"""Scenario1 minimal serial pipeline."""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from whale.aggregation.ads import (
    aggregate_availability,
    aggregate_power_curve_deviation,
    load_power_curve,
)
from whale.aggregation.periodic import aggregate_periodic
from whale.aggregation.realtime import aggregate_realtime
from whale.models import PipelineRunResult
from whale.processing.cleaner import PointCleaner
from whale.processing.normalizer import normalize_batch
from whale.raw_batch import build_raw_batch
from whale.scl_registry import build_registry_maps, parse_scl_registry
from whale.ingest.adapter.repositories.repositories import AdsRepository, DwdRepository, DwsRepository, OdsRepository


class Scenario1Pipeline:
    """Execute the scenario1 minimal closed loop in serial order.

    The pipeline orchestrates SCL parsing, ODS persistence, normalization,
    cleaning, DWD persistence, DWS aggregation, and ADS aggregation for the
    smallest end-to-end scenario currently implemented in the repository.
    """

    def __init__(
        self,
        ods_db_path: str | Path,
        dwd_db_path: str | Path,
        keyframe_interval_seconds: int = 10,
        dws_repository: DwsRepository | None = None,
        ads_repository: AdsRepository | None = None,
    ) -> None:
        """Initialize pipeline repositories and keyframe state.

        Args:
            ods_db_path: SQLite path used by the ODS repository.
            dwd_db_path: SQLite path used by the DWD repository.
            keyframe_interval_seconds: Minimum interval between persisted
                keyframes for the same turbine.
            dws_repository: Optional in-memory DWS repository override.
            ads_repository: Optional in-memory ADS repository override.
        """
        self.ods_repository = OdsRepository(ods_db_path)
        self.dwd_repository = DwdRepository(dwd_db_path)
        self.dws_repository = dws_repository or DwsRepository()
        self.ads_repository = ads_repository or AdsRepository()
        self.cleaner = PointCleaner()
        self.keyframe_interval = timedelta(seconds=keyframe_interval_seconds)
        self._last_keyframe_time: dict[str, datetime] = {}

    def run(
        self,
        scl_path: str | Path,
        raw_payloads: list[dict[str, Any]],
        power_curve_path: str | Path,
    ) -> PipelineRunResult:
        """Run the full scenario1 pipeline for a batch collection.

        Args:
            scl_path: Path to the minimal SCL registry file.
            raw_payloads: Mock OPC UA payloads to ingest in order.
            power_curve_path: Path to the theoretical power-curve CSV.

        Returns:
            Collected pipeline outputs and write counters for the run.
        """
        registry = parse_scl_registry(scl_path)
        registry_by_node, registry_by_code = build_registry_maps(registry)

        raw_batches_written = 0
        keyframes_written = 0
        dwd_records_written = 0

        for payload in raw_payloads:
            raw_batch = build_raw_batch(payload)
            self.ods_repository.write_raw_batch(raw_batch)
            raw_batches_written += 1

            if self._should_write_keyframe(raw_batch.turbine_id, raw_batch.recv_time):
                self.ods_repository.write_keyframe(
                    raw_batch.recv_time, raw_batch.turbine_id, raw_batch.raw_payload
                )
                self._last_keyframe_time[raw_batch.turbine_id] = raw_batch.recv_time
                keyframes_written += 1

            normalized_points = normalize_batch(raw_batch, registry_by_node, registry_by_code)
            for point in normalized_points:
                meta = registry_by_code[point.point_code]
                result = self.cleaner.clean(point, meta)
                self.dwd_repository.write_clean_result(result)
                dwd_records_written += 1

        dwd_records = self.dwd_repository.list_records()
        realtime_results = aggregate_realtime(dwd_records)
        periodic_results = aggregate_periodic(dwd_records)
        power_curve = load_power_curve(power_curve_path)
        power_curve_results = aggregate_power_curve_deviation(
            dwd_records, periodic_results, power_curve
        )
        availability_results = aggregate_availability(dwd_records)

        self.dws_repository.write_realtime(realtime_results)
        self.dws_repository.write_periodic(periodic_results)
        self.ads_repository.write_power_curve(power_curve_results)
        self.ads_repository.write_availability(availability_results)

        return PipelineRunResult(
            raw_batches_written=raw_batches_written,
            keyframes_written=keyframes_written,
            dwd_records_written=dwd_records_written,
            realtime_results=realtime_results,
            periodic_results=periodic_results,
            power_curve_results=power_curve_results,
            availability_results=availability_results,
        )

    def _should_write_keyframe(self, turbine_id: str, recv_time: datetime) -> bool:
        """Decide whether to persist a keyframe for the turbine."""
        last_time = self._last_keyframe_time.get(turbine_id)
        if last_time is None:
            return True
        return recv_time - last_time >= self.keyframe_interval
