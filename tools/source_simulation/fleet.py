"""Protocol-agnostic simulator fleet orchestration."""

from __future__ import annotations

import math
import random
import threading
import time
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime

from tools.source_simulation.adapters.registry import build_simulator
from tools.source_simulation.domain import (
    SharedPoint,
    SimulatedSource,
    UpdateConfig,
)
from tools.source_simulation.ports import SourceSimulator


@dataclass
class SourceSimulatorFleet:
    """Build, start and stop one homogeneous simulator fleet."""

    simulators: list[SourceSimulator]
    update_config: UpdateConfig
    _shared_points: tuple[SharedPoint, ...]
    _stop_updates: threading.Event = field(init=False, repr=False, default_factory=threading.Event)
    _update_thread: threading.Thread | None = field(init=False, repr=False, default=None)
    _update_points: tuple[SharedPoint, ...] = field(init=False, repr=False, default=())
    _random: random.Random = field(init=False, repr=False)

    def __post_init__(self) -> None:
        self._random = random.Random(20260506)

    @classmethod
    def create(
        cls,
        sources: Sequence[SimulatedSource],
        *,
        update_config: UpdateConfig | None = None,
    ) -> "SourceSimulatorFleet":
        """Build one fleet from externally prepared simulated sources."""
        resolved_config = update_config or UpdateConfig()
        source_list = list(sources)

        protocols = {
            source.connection.protocol.strip().lower().replace("_", "").replace("-", "")
            for source in source_list
        }
        if len(protocols) > 1:
            raise ValueError("A fleet can only contain one protocol")

        simulators: list[SourceSimulator] = []

        for source in source_list:
            simulators.append(build_simulator(source))

        return cls(
            simulators=simulators,
            update_config=resolved_config,
            _shared_points=cls._build_shared_points_from_sources(source_list),
        )

    @classmethod
    def _build_shared_points_from_sources(
        cls,
        sources: Sequence[SimulatedSource],
    ) -> tuple[SharedPoint, ...]:
        if not sources:
            return ()

        shared_points: list[SharedPoint] = []
        seen_paths: set[str] = set()
        for point in sources[0].points:
            if point.key in seen_paths:
                continue
            seen_paths.add(point.key)
            shared_points.append(
                SharedPoint(
                    path=point.key,
                    data_type=cls._normalize_point_data_type(point.data_type),
                    initial_value=point.initial_value,
                )
            )
        return tuple(shared_points)

    def _resolve_shared_points(self) -> tuple[SharedPoint, ...]:
        if not self.simulators:
            return ()

        discovered = self.simulators[0].discover_write_points()
        return tuple(
            SharedPoint(
                path=path,
                data_type=normalized_data_type,
                initial_value=self._build_random_value(normalized_data_type),
            )
            for path, data_type in discovered
            for normalized_data_type in [self._normalize_point_data_type(data_type)]
        )

    @staticmethod
    def _normalize_point_data_type(raw_data_type: str) -> str:
        normalized = raw_data_type.strip().upper()
        if normalized in {"BOOL", "BOOLEAN"}:
            return "BOOLEAN"
        if normalized in {
            "INT8",
            "INT16",
            "INT32",
            "INT64",
            "INT8U",
            "INT16U",
            "INT32U",
            "UINT8",
            "UINT16",
            "UINT32",
        }:
            return "INT32"
        if normalized in {"FLOAT", "FLOAT32", "FLOAT64", "DOUBLE"}:
            return "FLOAT64"
        if normalized in {"DATETIME", "TIMESTAMP"}:
            return "DATETIME"
        if normalized in {"STRING", "VISSTRING255", "TEXT"}:
            return "STRING"
        return "FLOAT64"

    def start(self) -> "SourceSimulatorFleet":
        for simulator in self.simulators:
            simulator.start()
        if not self._shared_points:
            self._shared_points = self._resolve_shared_points()
        self._update_points = tuple(self._select_points_for_update())
        self._start_update_loop()
        return self

    def stop(self) -> None:
        self._stop_update_loop()
        for simulator in reversed(self.simulators):
            simulator.stop()

    def __enter__(self) -> "SourceSimulatorFleet":
        return self.start()

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        self.stop()

    def _start_update_loop(self) -> None:
        if self._update_thread is not None or not self.simulators:
            return
        self._stop_updates.clear()
        self._update_thread = threading.Thread(
            target=self._run_update_loop,
            daemon=True,
            name="source-simulator-fleet-updates",
        )
        self._update_thread.start()

    def _stop_update_loop(self) -> None:
        if self._update_thread is None:
            return
        self._stop_updates.set()
        self._update_thread.join(timeout=max(self._tick_interval_seconds * 2.0, 1.0))
        self._update_thread = None

    @property
    def _tick_interval_seconds(self) -> float:
        return self.update_config.interval_seconds

    def _run_update_loop(self) -> None:
        interval_seconds = self._tick_interval_seconds
        next_run_at = time.monotonic() + interval_seconds
        while True:
            wait_seconds = max(0.0, next_run_at - time.monotonic())
            if self._stop_updates.wait(wait_seconds):
                break
            started_at = time.monotonic()
            self._apply_writes(self._build_next_writes())
            elapsed_seconds = time.monotonic() - started_at
            next_run_at = time.monotonic() + max(0.0, interval_seconds - elapsed_seconds)

    def _build_next_writes(self) -> dict[str, str | int | float | bool]:
        writes: dict[str, str | int | float | bool] = {}
        for point in self._update_points:
            writes[point.path] = self._build_random_value(point.data_type)
        return writes

    def _select_points_for_update(self) -> list[SharedPoint]:
        total = len(self._shared_points)
        if total == 0:
            return []

        if self.update_config.update_count is not None:
            selected_count = min(total, self.update_config.update_count)
        else:
            selected_count = math.floor(total * self.update_config.update_ratio)

        return list(self._shared_points[:selected_count])

    def _build_random_value(self, data_type: str) -> str | int | float | bool:
        if data_type == "BOOLEAN":
            return self._random.choice([True, False])
        if data_type == "INT32":
            return self._random.randint(0, 100)
        if data_type == "STRING":
            return self._random.choice(["foo", "bar", "baz"])
        if data_type == "DATETIME":
            return datetime.now(tz=UTC).isoformat()
        return self._random.uniform(0.0, 100.0)

    def _apply_writes(self, writes: dict[str, str | int | float | bool]) -> None:
        if not writes:
            return
        for simulator in self.simulators:
            simulator.writes(writes)
