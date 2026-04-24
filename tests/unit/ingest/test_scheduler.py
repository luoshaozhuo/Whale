"""Unit tests for the ingest runtime scheduler."""

from __future__ import annotations
from collections.abc import Callable
from datetime import UTC, datetime
from typing import cast

from whale.ingest.runtime.job_status import JobStatus
from whale.ingest.runtime.scheduler import SourceScheduler
from whale.ingest.runtime.scheduler_settings import SchedulerSettings
from whale.ingest.usecases.dtos.acquisition_status import AcquisitionStatus
from whale.ingest.usecases.dtos.pull_source_state_result import (
    PullSourceStateResult,
)
from whale.ingest.usecases.dtos.source_runtime_config_data import (
    SourceRuntimeConfigData,
)
from whale.ingest.usecases.pull_source_state_usecase import (
    PullSourceStateUseCase,
)
from whale.ingest.usecases.subscribe_source_state_usecase import (
    SubscribeSourceStateUseCase,
)


class FakeRuntimeConfigPort:
    """Fake runtime-config port that returns one fixed config list."""

    def __init__(self, configs: list[SourceRuntimeConfigData]) -> None:
        """Store the configs exposed to the scheduler."""
        self._configs = list(configs)

    def list_enabled(self) -> list[SourceRuntimeConfigData]:
        """Return the configured runtime configs."""
        return list(self._configs)


class FakePullSourceStateUseCase:
    """Fake use case that captures scheduler dispatch calls."""

    def __init__(
        self,
        status: AcquisitionStatus = AcquisitionStatus.SUCCEEDED,
    ) -> None:
        """Initialize one empty command capture list."""
        self._status = status
        self.runtime_config_batches: list[list[SourceRuntimeConfigData]] = []

    async def execute(
        self,
        runtime_configs: list[SourceRuntimeConfigData],
    ) -> list[PullSourceStateResult]:
        """Capture one merged short-task batch."""
        self.runtime_config_batches.append(runtime_configs)
        return [
            PullSourceStateResult(
                runtime_config_id=runtime_config.runtime_config_id,
                status=self._status,
                started_at=(now := datetime.now(tz=UTC)),
                ended_at=now,
                error_message=None if self._status is not AcquisitionStatus.FAILED else "boom",
            )
            for runtime_config in runtime_configs
        ]


class FakeSubscribeSourceStateUseCase:
    """Fake subscription use case that captures merged subscription calls."""

    def __init__(self) -> None:
        """Initialize subscription call capture."""
        self.calls: list[tuple[tuple[SourceRuntimeConfigData, ...], object]] = []

    async def execute(
        self,
        runtime_configs: tuple[SourceRuntimeConfigData, ...],
        stop_event: object,
    ) -> None:
        """Capture subscription runtime configs and stop signal."""
        self.calls.append((runtime_configs, stop_event))


def _build_runtime_config(
    runtime_config_id: int = 101,
    *,
    protocol: str = "opcua",
    acquisition_mode: str = "ONCE",
    interval_ms: int = 0,
) -> SourceRuntimeConfigData:
    """Build one minimal runtime config for scheduler tests."""
    return SourceRuntimeConfigData(
        runtime_config_id=runtime_config_id,
        source_id="WTG_01",
        protocol=protocol,
        acquisition_mode=acquisition_mode,
        interval_ms=interval_ms,
        enabled=True,
    )


def _get_start_callable(scheduler: SourceScheduler) -> Callable[[SourceRuntimeConfigData], None]:
    """Return the APScheduler job callable after registration."""
    jobs = scheduler._scheduler.get_jobs()  # noqa: SLF001
    assert len(jobs) == 1
    return cast(Callable[[SourceRuntimeConfigData], None], jobs[0].func)


def test_reload_registers_runtime_job_with_runtime_config() -> None:
    """Keep the runtime config in runtime job state."""
    runtime_config = _build_runtime_config(101)
    scheduler = SourceScheduler(
        runtime_config_port=FakeRuntimeConfigPort([runtime_config]),
        pull_source_state_usecase_factory=lambda: cast(
            PullSourceStateUseCase,
            FakePullSourceStateUseCase(),
        ),
        subscribe_source_state_usecase_factory=lambda: cast(
            SubscribeSourceStateUseCase,
            FakeSubscribeSourceStateUseCase(),
        ),
        settings=SchedulerSettings(scheduler_type="background"),
    )

    scheduler.reload()

    runtime_jobs = scheduler.get_runtime_jobs()
    assert len(runtime_jobs) == 1
    assert runtime_jobs[0].runtime_configs == (runtime_config,)
    assert runtime_jobs[0].aps_job_id == "once:101"
    assert runtime_jobs[0].status is JobStatus.SCHEDULED


def test_run_once_job_passes_runtime_config_snapshot_to_use_case() -> None:
    """Dispatch the runtime-config snapshot to the use case."""
    runtime_config = _build_runtime_config(101)
    use_case = FakePullSourceStateUseCase()
    scheduler = SourceScheduler(
        runtime_config_port=FakeRuntimeConfigPort([runtime_config]),
        pull_source_state_usecase_factory=lambda: cast(PullSourceStateUseCase, use_case),
        subscribe_source_state_usecase_factory=lambda: cast(
            SubscribeSourceStateUseCase,
            FakeSubscribeSourceStateUseCase(),
        ),
        settings=SchedulerSettings(scheduler_type="background"),
    )
    scheduler.reload()

    job_func = _get_start_callable(scheduler)
    runtime_job = scheduler.get_runtime_jobs()[0]

    assert runtime_job.status is JobStatus.SCHEDULED

    job_func(
        cast(SourceRuntimeConfigData, scheduler._scheduler.get_jobs()[0].args[0])
    )  # noqa: SLF001

    assert runtime_job.status is JobStatus.RUNNING
    assert use_case.runtime_config_batches == [[runtime_config]]


def test_run_once_job_marks_failed_result_as_failed_job() -> None:
    """Treat business FAILED results as failed scheduler jobs."""
    runtime_config = _build_runtime_config(101)
    use_case = FakePullSourceStateUseCase(status=AcquisitionStatus.FAILED)
    scheduler = SourceScheduler(
        runtime_config_port=FakeRuntimeConfigPort([runtime_config]),
        pull_source_state_usecase_factory=lambda: cast(
            PullSourceStateUseCase,
            use_case,
        ),
        subscribe_source_state_usecase_factory=lambda: cast(
            SubscribeSourceStateUseCase,
            FakeSubscribeSourceStateUseCase(),
        ),
        settings=SchedulerSettings(scheduler_type="background"),
    )
    scheduler.reload()

    _get_start_callable(scheduler)(runtime_config)
    scheduler._on_job_executed_or_failed(  # noqa: SLF001
        type("Event", (), {"job_id": "once:101", "exception": None})()
    )

    runtime_job = scheduler.get_runtime_jobs()[0]
    assert runtime_job.status is JobStatus.FAILED
    assert runtime_job.last_result is not None
    assert runtime_job.last_result.status is AcquisitionStatus.FAILED


def test_run_once_job_keeps_empty_result_non_failed() -> None:
    """Treat EMPTY as one non-failing business outcome."""
    runtime_config = _build_runtime_config(101)
    use_case = FakePullSourceStateUseCase(status=AcquisitionStatus.EMPTY)
    scheduler = SourceScheduler(
        runtime_config_port=FakeRuntimeConfigPort([runtime_config]),
        pull_source_state_usecase_factory=lambda: cast(
            PullSourceStateUseCase,
            use_case,
        ),
        subscribe_source_state_usecase_factory=lambda: cast(
            SubscribeSourceStateUseCase,
            FakeSubscribeSourceStateUseCase(),
        ),
        settings=SchedulerSettings(scheduler_type="background"),
    )
    scheduler.reload()

    _get_start_callable(scheduler)(runtime_config)
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
    use_case = FakePullSourceStateUseCase(status=AcquisitionStatus.DISABLED)
    scheduler = SourceScheduler(
        runtime_config_port=FakeRuntimeConfigPort([runtime_config]),
        pull_source_state_usecase_factory=lambda: cast(
            PullSourceStateUseCase,
            use_case,
        ),
        subscribe_source_state_usecase_factory=lambda: cast(
            SubscribeSourceStateUseCase,
            FakeSubscribeSourceStateUseCase(),
        ),
        settings=SchedulerSettings(scheduler_type="background"),
    )
    scheduler.reload()

    _get_start_callable(scheduler)(runtime_config)
    scheduler._on_job_executed_or_failed(  # noqa: SLF001
        type("Event", (), {"job_id": "once:101", "exception": None})()
    )

    runtime_job = scheduler.get_runtime_jobs()[0]
    assert runtime_job.status is JobStatus.FINISHED
    assert runtime_job.last_result is not None
    assert runtime_job.last_result.status is AcquisitionStatus.DISABLED
    assert scheduler.has_failures() is False


def test_reload_merges_polling_jobs_by_interval() -> None:
    """Register one APScheduler polling job per shared interval."""
    first = _build_runtime_config(101, acquisition_mode="POLLING", interval_ms=1000)
    second = _build_runtime_config(102, acquisition_mode="POLLING", interval_ms=1000)
    scheduler = SourceScheduler(
        runtime_config_port=FakeRuntimeConfigPort([first, second]),
        pull_source_state_usecase_factory=lambda: cast(
            PullSourceStateUseCase,
            FakePullSourceStateUseCase(),
        ),
        subscribe_source_state_usecase_factory=lambda: cast(
            SubscribeSourceStateUseCase,
            FakeSubscribeSourceStateUseCase(),
        ),
        settings=SchedulerSettings(scheduler_type="background"),
    )

    scheduler.reload()

    runtime_jobs = scheduler.get_runtime_jobs()
    assert len(runtime_jobs) == 1
    assert runtime_jobs[0].aps_job_id == "polling:opcua:1000"
    assert runtime_jobs[0].runtime_configs == (first, second)


def test_reload_splits_polling_jobs_by_protocol() -> None:
    """Do not merge polling configs from different protocols."""
    opcua_config = _build_runtime_config(101, acquisition_mode="POLLING", interval_ms=1000)
    modbus_config = _build_runtime_config(
        102,
        protocol="modbus",
        acquisition_mode="POLLING",
        interval_ms=1000,
    )
    scheduler = SourceScheduler(
        runtime_config_port=FakeRuntimeConfigPort([opcua_config, modbus_config]),
        pull_source_state_usecase_factory=lambda: cast(
            PullSourceStateUseCase,
            FakePullSourceStateUseCase(),
        ),
        subscribe_source_state_usecase_factory=lambda: cast(
            SubscribeSourceStateUseCase,
            FakeSubscribeSourceStateUseCase(),
        ),
        settings=SchedulerSettings(scheduler_type="background"),
    )

    scheduler.reload()

    assert {job.aps_job_id for job in scheduler.get_runtime_jobs()} == {
        "polling:modbus:1000",
        "polling:opcua:1000",
    }


def test_polling_job_executes_merged_batch_with_one_use_case() -> None:
    """Dispatch same-interval polling configs as one short batch."""
    first = _build_runtime_config(101, acquisition_mode="POLLING", interval_ms=1000)
    second = _build_runtime_config(102, acquisition_mode="POLLING", interval_ms=1000)
    use_case = FakePullSourceStateUseCase()
    scheduler = SourceScheduler(
        runtime_config_port=FakeRuntimeConfigPort([first, second]),
        pull_source_state_usecase_factory=lambda: cast(PullSourceStateUseCase, use_case),
        subscribe_source_state_usecase_factory=lambda: cast(
            SubscribeSourceStateUseCase,
            FakeSubscribeSourceStateUseCase(),
        ),
        settings=SchedulerSettings(scheduler_type="background"),
    )
    scheduler.reload()

    job = scheduler._scheduler.get_jobs()[0]  # noqa: SLF001
    cast(Callable[[tuple[SourceRuntimeConfigData, ...]], None], job.func)(
        cast(tuple[SourceRuntimeConfigData, ...], job.args[0])
    )

    assert use_case.runtime_config_batches == [[first, second]]


def test_subscription_job_sets_stop_event_on_stop() -> None:
    """Start subscription as one merged long-running job with a stop signal."""
    first = _build_runtime_config(101, acquisition_mode="SUBSCRIPTION")
    second = _build_runtime_config(102, acquisition_mode="SUBSCRIPTION")
    use_case = FakeSubscribeSourceStateUseCase()
    scheduler = SourceScheduler(
        runtime_config_port=FakeRuntimeConfigPort([first, second]),
        pull_source_state_usecase_factory=lambda: cast(
            PullSourceStateUseCase,
            FakePullSourceStateUseCase(),
        ),
        subscribe_source_state_usecase_factory=lambda: cast(
            SubscribeSourceStateUseCase,
            use_case,
        ),
        settings=SchedulerSettings(scheduler_type="background"),
    )
    scheduler.reload()

    job = scheduler._scheduler.get_jobs()[0]  # noqa: SLF001
    cast(Callable[[tuple[SourceRuntimeConfigData, ...], object], None], job.func)(
        cast(tuple[SourceRuntimeConfigData, ...], job.args[0]),
        job.args[1],
    )
    scheduler.stop(wait=False)

    assert use_case.calls[0][0] == (first, second)
    assert getattr(use_case.calls[0][1], "is_set")()


def test_reload_splits_subscription_jobs_by_protocol() -> None:
    """Do not merge subscription configs from different protocols."""
    opcua_config = _build_runtime_config(101, acquisition_mode="SUBSCRIPTION")
    modbus_config = _build_runtime_config(
        102,
        protocol="modbus",
        acquisition_mode="SUBSCRIPTION",
    )
    scheduler = SourceScheduler(
        runtime_config_port=FakeRuntimeConfigPort([opcua_config, modbus_config]),
        pull_source_state_usecase_factory=lambda: cast(
            PullSourceStateUseCase,
            FakePullSourceStateUseCase(),
        ),
        subscribe_source_state_usecase_factory=lambda: cast(
            SubscribeSourceStateUseCase,
            FakeSubscribeSourceStateUseCase(),
        ),
        settings=SchedulerSettings(scheduler_type="background"),
    )

    scheduler.reload()

    assert {job.aps_job_id for job in scheduler.get_runtime_jobs()} == {
        "subscription:modbus",
        "subscription:opcua",
    }
