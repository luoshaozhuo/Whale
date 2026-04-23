"""Unit tests for the ingest runtime scheduler."""

from __future__ import annotations

from collections.abc import Callable
from typing import cast

from whale.ingest.runtime.job_status import JobStatus
from whale.ingest.runtime.scheduler import SourceScheduler
from whale.ingest.runtime.scheduler_settings import SchedulerSettings
from whale.ingest.usecases.dtos.acquisition_status import AcquisitionStatus
from whale.ingest.usecases.dtos.refresh_source_state_result import (
    RefreshSourceStateResult,
)
from whale.ingest.usecases.dtos.source_runtime_config_data import (
    SourceRuntimeConfigData,
)
from whale.ingest.usecases.refresh_source_state_usecase import (
    RefreshSourceStateUseCase,
)


class FakeRuntimeConfigPort:
    """Fake runtime-config port that returns one fixed config list."""

    def __init__(self, configs: list[SourceRuntimeConfigData]) -> None:
        """Store the configs exposed to the scheduler."""
        self._configs = list(configs)

    def list_enabled(self) -> list[SourceRuntimeConfigData]:
        """Return the configured runtime configs."""
        return list(self._configs)

    def get_by_id(self, runtime_config_id: int) -> SourceRuntimeConfigData:
        """Return one runtime config by id."""
        for config in self._configs:
            if config.runtime_config_id == runtime_config_id:
                return config
        raise LookupError(runtime_config_id)


class FakeRefreshSourceStateUseCase:
    """Fake use case that captures scheduler dispatch calls."""

    def __init__(
        self,
        status: AcquisitionStatus = AcquisitionStatus.SUCCEEDED,
    ) -> None:
        """Initialize one empty command capture list."""
        self._status = status
        self.commands: list[object] = []

    def execute(self, command: object) -> RefreshSourceStateResult:
        """Capture the command and return one configured result."""
        self.commands.append(command)
        runtime_config_id = getattr(command, "runtime_config_id")
        return RefreshSourceStateResult(
            runtime_config_id=runtime_config_id,
            source_id="WTG_01",
            status=self._status,
            received_count=1 if self._status is AcquisitionStatus.SUCCEEDED else 0,
            updated_count=1 if self._status is AcquisitionStatus.SUCCEEDED else 0,
            error_message=None if self._status is not AcquisitionStatus.FAILED else "boom",
        )


def _build_runtime_config(runtime_config_id: int = 101) -> SourceRuntimeConfigData:
    """Build one minimal runtime config for scheduler tests."""
    return SourceRuntimeConfigData(
        runtime_config_id=runtime_config_id,
        source_id="WTG_01",
        protocol="opcua",
        acquisition_mode="ONCE",
        interval_ms=0,
        enabled=True,
    )


def _get_start_callable(scheduler: SourceScheduler) -> Callable[[int], None]:
    """Return the APScheduler job callable after registration."""
    jobs = scheduler._scheduler.get_jobs()  # noqa: SLF001
    assert len(jobs) == 1
    return cast(Callable[[int], None], jobs[0].func)


def test_reload_registers_runtime_job_with_runtime_config() -> None:
    """Keep the runtime config in runtime job state."""
    runtime_config = _build_runtime_config(101)
    scheduler = SourceScheduler(
        runtime_config_port=FakeRuntimeConfigPort([runtime_config]),
        refresh_source_state_usecase=cast(
            RefreshSourceStateUseCase, FakeRefreshSourceStateUseCase()
        ),
        settings=SchedulerSettings(scheduler_type="background"),
    )

    scheduler.reload()

    runtime_jobs = scheduler.get_runtime_jobs()
    assert len(runtime_jobs) == 1
    assert runtime_jobs[0].runtime_config is runtime_config
    assert runtime_jobs[0].aps_job_id == "once:101"
    assert runtime_jobs[0].status is JobStatus.SCHEDULED


def test_run_once_job_passes_runtime_config_id_to_use_case() -> None:
    """Dispatch only the runtime-config id to the use case."""
    runtime_config = _build_runtime_config(101)
    use_case = FakeRefreshSourceStateUseCase()
    scheduler = SourceScheduler(
        runtime_config_port=FakeRuntimeConfigPort([runtime_config]),
        refresh_source_state_usecase=cast(RefreshSourceStateUseCase, use_case),
        settings=SchedulerSettings(scheduler_type="background"),
    )
    scheduler.reload()

    job_func = _get_start_callable(scheduler)
    runtime_job = scheduler.get_runtime_jobs()[0]

    assert runtime_job.status is JobStatus.SCHEDULED

    job_func(cast(int, scheduler._scheduler.get_jobs()[0].args[0]))  # noqa: SLF001

    assert runtime_job.status is JobStatus.RUNNING
    assert len(use_case.commands) == 1
    assert getattr(use_case.commands[0], "runtime_config_id") == 101


def test_run_once_job_marks_failed_result_as_failed_job() -> None:
    """Treat business FAILED results as failed scheduler jobs."""
    runtime_config = _build_runtime_config(101)
    scheduler = SourceScheduler(
        runtime_config_port=FakeRuntimeConfigPort([runtime_config]),
        refresh_source_state_usecase=cast(
            RefreshSourceStateUseCase,
            FakeRefreshSourceStateUseCase(status=AcquisitionStatus.FAILED),
        ),
        settings=SchedulerSettings(scheduler_type="background"),
    )
    scheduler.reload()

    _get_start_callable(scheduler)(101)

    runtime_job = scheduler.get_runtime_jobs()[0]
    assert runtime_job.status is JobStatus.FAILED
    assert runtime_job.last_result is not None
    assert runtime_job.last_result.status is AcquisitionStatus.FAILED


def test_run_once_job_keeps_empty_result_non_failed() -> None:
    """Treat EMPTY as one non-failing business outcome."""
    runtime_config = _build_runtime_config(101)
    scheduler = SourceScheduler(
        runtime_config_port=FakeRuntimeConfigPort([runtime_config]),
        refresh_source_state_usecase=cast(
            RefreshSourceStateUseCase,
            FakeRefreshSourceStateUseCase(status=AcquisitionStatus.EMPTY),
        ),
        settings=SchedulerSettings(scheduler_type="background"),
    )
    scheduler.reload()

    _get_start_callable(scheduler)(101)
    scheduler._on_job_executed_or_failed(  # noqa: SLF001
        type("Event", (), {"job_id": "once:101", "exception": None})()
    )

    runtime_job = scheduler.get_runtime_jobs()[0]
    assert runtime_job.status is JobStatus.FINISHED
    assert runtime_job.last_result is not None
    assert runtime_job.last_result.status is AcquisitionStatus.EMPTY
    assert scheduler.has_failures() is False


def test_run_once_job_keeps_disabled_result_non_failed() -> None:
    """Treat DISABLED as one non-failing business outcome."""
    runtime_config = _build_runtime_config(101)
    scheduler = SourceScheduler(
        runtime_config_port=FakeRuntimeConfigPort([runtime_config]),
        refresh_source_state_usecase=cast(
            RefreshSourceStateUseCase,
            FakeRefreshSourceStateUseCase(status=AcquisitionStatus.DISABLED),
        ),
        settings=SchedulerSettings(scheduler_type="background"),
    )
    scheduler.reload()

    _get_start_callable(scheduler)(101)
    scheduler._on_job_executed_or_failed(  # noqa: SLF001
        type("Event", (), {"job_id": "once:101", "exception": None})()
    )

    runtime_job = scheduler.get_runtime_jobs()[0]
    assert runtime_job.status is JobStatus.FINISHED
    assert runtime_job.last_result is not None
    assert runtime_job.last_result.status is AcquisitionStatus.DISABLED
    assert scheduler.has_failures() is False
