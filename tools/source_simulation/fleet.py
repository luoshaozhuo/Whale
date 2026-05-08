"""Protocol-agnostic simulator fleet orchestration."""

from __future__ import annotations

import math
import multiprocessing
import queue
import random
import time
import traceback
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from multiprocessing import queues, synchronize

from tools.source_simulation.adapters.registry import build_simulator
from tools.source_simulation.domain import SimulatedPoint, SimulatedSource, UpdateConfig

_STARTUP_TIMEOUT_SECONDS = 10.0
_READY_POLL_SECONDS = 0.05


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


def _select_points_for_update(
    points: Sequence[SimulatedPoint],
    update_config: UpdateConfig,
) -> tuple[SimulatedPoint, ...]:
    total = len(points)
    if total == 0:
        return ()

    if update_config.update_count is not None:
        selected_count = min(total, update_config.update_count)
    else:
        selected_count = math.floor(total * update_config.update_ratio)

    return tuple(points[:selected_count])


def _build_random_value(
    rng: random.Random,
    data_type: str,
) -> str | int | float | bool:
    normalized_data_type = _normalize_point_data_type(data_type)
    if normalized_data_type == "BOOLEAN":
        return rng.choice([True, False])
    if normalized_data_type == "INT32":
        return rng.randint(0, 100)
    if normalized_data_type == "STRING":
        return rng.choice(["foo", "bar", "baz"])
    if normalized_data_type == "DATETIME":
        return datetime.now(tz=UTC).isoformat()
    return rng.uniform(0.0, 100.0)


def _build_update_writes(
    points: Sequence[SimulatedPoint],
    rng: random.Random,
) -> dict[str, str | int | float | bool]:
    writes: dict[str, str | int | float | bool] = {}
    for point in points:
        writes[point.key] = _build_random_value(rng, point.data_type)
    return writes


def _run_simulator_process(
    source: SimulatedSource,
    update_config: UpdateConfig,
    stop_event: synchronize.Event,
    ready_event: synchronize.Event,
    error_queue: queues.Queue[str],
) -> None:
    simulator = None
    try:
        simulator = build_simulator(source)
        simulator.start()

        # 一个 source 对应一个独立子进程，尽量贴近真实“一个设备一个 server”。
        ready_event.set()

        # 周期写入放在子进程内部完成，主进程只负责生命周期，不再跨进程持有 simulator。
        update_points = _select_points_for_update(source.points, update_config)
        rng = random.Random(
            f"{source.connection.name}:{source.connection.host}:{source.connection.port}"
        )
        next_update_at = time.monotonic() + update_config.interval_seconds

        while not stop_event.is_set():
            if not update_config.enabled:
                stop_event.wait(0.1)
                continue

            now = time.monotonic()
            if now >= next_update_at:
                writes = _build_update_writes(update_points, rng)
                if writes:
                    simulator.writes(writes)

                next_update_at += update_config.interval_seconds
                while next_update_at <= now:
                    next_update_at += update_config.interval_seconds

            wait_seconds = min(0.05, max(0.0, next_update_at - time.monotonic()))
            stop_event.wait(wait_seconds)
    except Exception as exc:
        error_queue.put(
            (
                f"Simulator process failed for source={source.connection.name} "
                f"endpoint={source.connection.host}:{source.connection.port}: {exc}\n"
                f"{traceback.format_exc()}"
            )
        )
    finally:
        if simulator is not None:
            simulator.stop()


@dataclass
class SourceSimulatorFleet:
    """Build, start and stop one homogeneous simulator fleet."""

    sources: tuple[SimulatedSource, ...]
    update_config: UpdateConfig
    join_timeout_seconds: float = 5.0
    _processes: list[multiprocessing.Process] = field(init=False, repr=False, default_factory=list)
    _stop_events: list[synchronize.Event] = field(init=False, repr=False, default_factory=list)
    _ready_events: list[synchronize.Event] = field(init=False, repr=False, default_factory=list)
    _error_queue: queues.Queue[str] | None = field(init=False, repr=False, default=None)

    @classmethod
    def create(
        cls,
        sources: Sequence[SimulatedSource],
        *,
        update_config: UpdateConfig | None = None,
    ) -> "SourceSimulatorFleet":
        """Build one fleet from externally prepared simulated sources."""
        resolved_config = update_config or UpdateConfig()
        source_list = tuple(sources)

        if not source_list:
            raise ValueError("A fleet must contain at least one source")

        protocols = {
            source.connection.protocol.strip().lower().replace("_", "").replace("-", "")
            for source in source_list
        }
        if len(protocols) > 1:
            raise ValueError("A fleet can only contain one protocol")

        return cls(
            sources=source_list,
            update_config=resolved_config,
        )

    def start(self) -> "SourceSimulatorFleet":
        if self._processes:
            return self

        try:
            self._start_processes()
            self._wait_until_ready()
        except Exception:
            self.stop()
            raise

        return self

    def stop(self) -> None:
        if not self._processes:
            self._close_error_queue()
            return

        # 先通知所有子进程自行收尾，给正常 stop 一个优先机会。
        for stop_event in self._stop_events:
            stop_event.set()

        for process in self._processes:
            process.join(timeout=self.join_timeout_seconds)

        # 如果子进程没有按时退出，再逐级升级到 terminate / kill，避免测试后残留端口。
        for process in self._processes:
            if process.is_alive():
                process.terminate()

        for process in self._processes:
            process.join(timeout=self.join_timeout_seconds)

        for process in self._processes:
            if process.is_alive():
                process.kill()

        for process in self._processes:
            process.join()

        self._processes.clear()
        self._stop_events.clear()
        self._ready_events.clear()
        self._close_error_queue()

    def __enter__(self) -> "SourceSimulatorFleet":
        return self.start()

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        self.stop()

    def _start_processes(self) -> None:
        context = multiprocessing.get_context()
        self._error_queue = context.Queue()

        for index, source in enumerate(self.sources):
            # ready_event 用来表示子进程已完成 server.start()；
            # stop_event 用来请求子进程退出；
            # error_queue 用来把启动失败原因回传给主进程。
            stop_event = context.Event()
            ready_event = context.Event()
            process = context.Process(
                target=_run_simulator_process,
                name=f"source-simulator-{index + 1}",
                args=(
                    source,
                    self.update_config,
                    stop_event,
                    ready_event,
                    self._error_queue,
                ),
            )
            process.start()
            self._processes.append(process)
            self._stop_events.append(stop_event)
            self._ready_events.append(ready_event)

    def _wait_until_ready(self) -> None:
        deadline = time.monotonic() + _STARTUP_TIMEOUT_SECONDS
        pending_indices = set(range(len(self._ready_events)))

        while pending_indices:
            startup_errors = self._drain_startup_errors()
            if startup_errors:
                raise RuntimeError("Failed to start simulator fleet:\n" + "\n".join(startup_errors))

            for index in tuple(pending_indices):
                if self._ready_events[index].is_set():
                    pending_indices.remove(index)
                    continue

                process = self._processes[index]
                if not process.is_alive():
                    raise RuntimeError(
                        "Simulator process exited before ready: "
                        f"name={process.name} exitcode={process.exitcode}"
                    )

            if not pending_indices:
                break

            remaining_seconds = deadline - time.monotonic()
            if remaining_seconds <= 0:
                raise RuntimeError("Timed out waiting for simulator fleet readiness")

            for index in tuple(pending_indices):
                if self._ready_events[index].wait(
                    timeout=min(_READY_POLL_SECONDS, remaining_seconds)
                ):
                    pending_indices.remove(index)

    def _drain_startup_errors(self) -> list[str]:
        if self._error_queue is None:
            return []

        errors: list[str] = []
        while True:
            try:
                errors.append(self._error_queue.get_nowait())
            except queue.Empty:
                return errors

    def _close_error_queue(self) -> None:
        if self._error_queue is None:
            return
        self._error_queue.close()
        self._error_queue.join_thread()
        self._error_queue = None
