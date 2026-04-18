"""Repositories used by scenario1 pipeline."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import cast

from whale.scenario1.models import (
    AdsAvailability,
    AdsPowerCurveDeviation,
    CleanResult,
    DwdRecord,
    DwsPeriodicAggregate,
    DwsRealtimeAggregate,
    RawBatch,
    ScalarValue,
)
from whale.shared.enums.quality import QualityCode, RunState
from whale.shared.utils.time import parse_iso_datetime


class OdsRepository:
    """Persist ODS raw batches and keyframes in SQLite."""

    def __init__(self, db_path: str | Path) -> None:
        """Initialize the repository and create required SQLite tables.

        Args:
            db_path: SQLite database path for ODS storage.
        """
        self._db_path = str(db_path)
        self._init_db()

    def write_raw_batch(self, batch: RawBatch) -> None:
        """Persist one raw batch into ODS.

        Args:
            batch: Raw batch model to store.
        """
        with sqlite3.connect(self._db_path) as conn:
            conn.execute(
                """
                INSERT INTO raw_batches(batch_id, recv_time, turbine_id, raw_payload)
                VALUES (?, ?, ?, ?)
                """,
                (
                    batch.batch_id,
                    batch.recv_time.isoformat(),
                    batch.turbine_id,
                    json.dumps(batch.raw_payload, sort_keys=True),
                ),
            )

    def write_keyframe(
        self, frame_time: datetime, turbine_id: str, payload: dict[str, object]
    ) -> None:
        """Persist one turbine keyframe snapshot into ODS.

        Args:
            frame_time: UTC timestamp for the keyframe snapshot.
            turbine_id: Turbine identifier that owns the snapshot.
            payload: Raw payload fragment kept for replay and traceability.
        """
        with sqlite3.connect(self._db_path) as conn:
            conn.execute(
                """
                INSERT INTO keyframes(frame_time, turbine_id, payload)
                VALUES (?, ?, ?)
                """,
                (
                    frame_time.isoformat(),
                    turbine_id,
                    json.dumps(payload, sort_keys=True),
                ),
            )

    def count_raw_batches(self) -> int:
        """Return the number of raw batches currently stored."""
        return self._count("raw_batches")

    def count_keyframes(self) -> int:
        """Return the number of keyframes currently stored."""
        return self._count("keyframes")

    def _count(self, table: str) -> int:
        """Count rows in a table."""
        with sqlite3.connect(self._db_path) as conn:
            row = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()
        return int(row[0]) if row else 0

    def _init_db(self) -> None:
        """Create ODS tables if they do not exist."""
        with sqlite3.connect(self._db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS raw_batches(
                    batch_id TEXT PRIMARY KEY,
                    recv_time TEXT NOT NULL,
                    turbine_id TEXT NOT NULL,
                    raw_payload TEXT NOT NULL
                )
                """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS keyframes(
                    frame_time TEXT NOT NULL,
                    turbine_id TEXT NOT NULL,
                    payload TEXT NOT NULL
                )
                """)


class DwdRepository:
    """Persist cleaned DWD records in SQLite."""

    def __init__(self, db_path: str | Path) -> None:
        """Initialize the DWD repository and create required tables.

        Args:
            db_path: SQLite database path for DWD storage.
        """
        self._db_path = str(db_path)
        self._init_db()

    def write_clean_result(self, result: CleanResult) -> None:
        """Persist one clean result as a DWD record.

        Args:
            result: Cleaner output to serialize and store.
        """
        point = result.normalized_point
        value_json, value_kind = _serialize_value(point.value)
        with sqlite3.connect(self._db_path) as conn:
            conn.execute(
                """
                INSERT INTO dwd_records(
                    ts, ingest_time, turbine_id, point_code, value_json, value_kind, quality_code
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    point.event_time.isoformat(),
                    point.ingest_time.isoformat(),
                    point.turbine_id,
                    point.point_code,
                    value_json,
                    value_kind,
                    result.quality_code.value,
                ),
            )

    def list_records(self) -> list[DwdRecord]:
        """Return all persisted DWD records ordered by timestamp.

        Returns:
            Cleaned DWD records reconstructed from SQLite storage.
        """
        with sqlite3.connect(self._db_path) as conn:
            rows = conn.execute("""
                SELECT ts, ingest_time, turbine_id, point_code, value_json, value_kind, quality_code
                FROM dwd_records
                ORDER BY ts, point_code
                """).fetchall()

        return [
            DwdRecord(
                ts=parse_iso_datetime(row[0]),
                ingest_time=parse_iso_datetime(row[1]),
                turbine_id=row[2],
                point_code=row[3],
                value=_deserialize_value(row[4], row[5]),
                quality_code=QualityCode(row[6]),
            )
            for row in rows
        ]

    def count(self) -> int:
        """Return the number of DWD records currently stored."""
        with sqlite3.connect(self._db_path) as conn:
            row = conn.execute("SELECT COUNT(*) FROM dwd_records").fetchone()
        return int(row[0]) if row else 0

    def _init_db(self) -> None:
        """Create DWD table if needed."""
        with sqlite3.connect(self._db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS dwd_records(
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    ts TEXT NOT NULL,
                    ingest_time TEXT NOT NULL,
                    turbine_id TEXT NOT NULL,
                    point_code TEXT NOT NULL,
                    value_json TEXT NOT NULL,
                    value_kind TEXT NOT NULL,
                    quality_code TEXT NOT NULL
                )
                """)


class DwsRepository:
    """Keep DWS aggregate results in memory for the current pipeline run."""

    def __init__(self) -> None:
        """Initialize in-memory storage."""
        self._realtime: list[DwsRealtimeAggregate] = []
        self._periodic: list[DwsPeriodicAggregate] = []

    def write_realtime(self, results: list[DwsRealtimeAggregate]) -> None:
        """Store realtime DWS aggregate results.

        Args:
            results: Realtime aggregates to append to in-memory storage.
        """
        self._realtime.extend(results)

    def write_periodic(self, results: list[DwsPeriodicAggregate]) -> None:
        """Store periodic DWS aggregate results.

        Args:
            results: Periodic aggregates to append to in-memory storage.
        """
        self._periodic.extend(results)

    def list_realtime(self) -> list[DwsRealtimeAggregate]:
        """Return a copy of the stored realtime DWS results."""
        return list(self._realtime)

    def list_periodic(self) -> list[DwsPeriodicAggregate]:
        """Return a copy of the stored periodic DWS results."""
        return list(self._periodic)


class AdsRepository:
    """Keep ADS aggregate results in memory for the current pipeline run."""

    def __init__(self) -> None:
        """Initialize in-memory ADS storage."""
        self._power_curve: list[AdsPowerCurveDeviation] = []
        self._availability: list[AdsAvailability] = []

    def write_power_curve(self, results: list[AdsPowerCurveDeviation]) -> None:
        """Store ADS power-curve deviation results.

        Args:
            results: ADS power-curve deviation aggregates to append.
        """
        self._power_curve.extend(results)

    def write_availability(self, results: list[AdsAvailability]) -> None:
        """Store ADS availability results.

        Args:
            results: ADS availability aggregates to append.
        """
        self._availability.extend(results)

    def list_power_curve(self) -> list[AdsPowerCurveDeviation]:
        """Return a copy of the stored ADS power-curve results."""
        return list(self._power_curve)

    def list_availability(self) -> list[AdsAvailability]:
        """Return a copy of the stored ADS availability results."""
        return list(self._availability)


def _serialize_value(value: ScalarValue) -> tuple[str, str]:
    """Serialize a DWD value for SQLite storage."""
    if isinstance(value, RunState):
        return json.dumps(value.value), "run_state"
    if value is None:
        return json.dumps(None), "null"
    if isinstance(value, bool):
        return json.dumps(value), "bool"
    if isinstance(value, int) and not isinstance(value, bool):
        return json.dumps(value), "int"
    if isinstance(value, float):
        return json.dumps(value), "float"
    return json.dumps(value), "str"


def _deserialize_value(value_json: str, value_kind: str) -> ScalarValue:
    """Deserialize SQLite DWD values back into Python objects."""
    raw_value = cast(ScalarValue, json.loads(value_json))
    if value_kind == "run_state":
        assert isinstance(raw_value, str)
        return RunState(raw_value)
    if value_kind == "int":
        assert isinstance(raw_value, (int, float, str))
        return int(raw_value)
    if value_kind == "float":
        assert isinstance(raw_value, (int, float, str))
        return float(raw_value)
    return raw_value
