"""Unit tests for the ingest runtime scheduler."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from typing import cast

from whale.ingest.runtime.job_status import JobStatus
from whale.ingest.runtime.scheduler import SourceScheduler
from whale.ingest.runtime.scheduler_settings import SchedulerSettings
from whale.ingest.usecases.build_runtime_plan_usecase import RuntimePlanBuildUseCase
from whale.ingest.usecases.dtos.acquisition_status import AcquisitionStatus
from whale.ingest.usecases.dtos.source_acquisition_execution_plan import (
    SourceAcquisitionExecutionPlan,
)
from whale.ingest.usecases.dtos.source_connection_data import SourceConnectionData
from whale.ingest.usecases.dtos.source_runtime_config_data import (
    SourceRuntimeConfigData,
)
from whale.ingest.usecases.dtos.source_state_acquisition_result import (
    SourceStateAcquisitionResult,
)
from whale.ingest.usecases.execute_source_acquisition_usecase import (
    ExecuteSourceAcquisitionUseCase,
)
from whale.ingest.usecases.subscribe_source_state_usecase import (
    SubscribeSourceStateUseCase,
)


class FakeRuntimeConfigPort:
    """Fake runtime-config port that returns one fixed config list."""

    def __init__(self, configs: list[SourceRuntimeConfigData]) -> None:
        self._configs = list(configs)

    def list_enabled(self) -> list[SourceRuntimeConfigData]:
        return list(self._configs)


class FakePlanBuildUseCase:
    """Fake plan-build use case that captures configs and returns simple plans."""

    def __init__(self) -> None:
        self.captured_configs: list[list[SourceRuntimeConfigData]] = []

    def build_plans(self, configs: list[SourceRuntimeConfigData]) -> list[SourceAcquisitionExecutionPlan]:
        self.captured_configs.append(list(configs))
        return [
            SourceAcquisitionExecutionPlan(
                plan_id=f"plan-{cfg.runtime_config_id}",
                task_id=cfg.runtime_config_id,
                ld_instance_id=0,
                acquisition_mode=cfg.acquisition_mode,
                protocol=cfg.protocol,
                endpoint_config=SourceConnectionData(endpoint="opc.tcp://127.0.0.1:4840"),
                request_items=[],
                request_timeout_ms=500,
                freshness_timeout_ms=30000,
                alive_timeout_ms=60000,
            )
            for cfg in configs
        ]

    def build_plans_from_enabled(self) -> list[SourceAcquisitionExecutionPlan]:
        return []


class FakeExecuteSourceAcquisitionUseCase:
    """Fake use case that captures plan dispatch calls."""

    def __init__(
        self,
        status: AcquisitionStatus = AcquisitionStatus.SUCCEEDED,
    ) -> None:
        self._status = status
        self.plan_batches: list[list[SourceAcquisitionExecutionPlan]] = []

    async def execute(
        self,
        plans: list[SourceAcquisitionExecutionPlan],
    ) -> list[SourceStateAcquisitionResult]:
        self.plan_batches.append(list(plans))
        return [
            SourceStateAcquisitionResult(
                plan_id=plan.plan_id,
                task_id=plan.task_id,
                ld_instance_id=plan.ld_instance_id,
                status=self._status,
                started_at=(now := datetime.now(tz=UTC)),
                ended_at=now,
                error_message=None if self._status is not AcquisitionStatus.FAILED else "boom",
            )
            for plan in plans
        ]


class FakeSubscribeSourceStateUseCase:
    """Fake subscription use case that captures merged subscription calls."""

    def __init__(self) -> None:
        self.calls: list[tuple[tuple[SourceRuntimeConfigData, ...], object]] = []

    async def execute(
        self,
        runtime_configs: tuple[SourceRuntimeConfigData, ...],
        stop_event: object,
    ) -> None:
        self.calls.append((runtime_configs, stop_event))


def _build_runtime_config(
    runtime_config_id: int = 101,
    *,
    protocol: str = "opcua",
    acquisition_mode: str = "ONCE",
    interval_ms: int = 0,
) -> SourceRuntimeConfigData:
    return SourceRuntimeConfigData(
        runtime_config_id=runtime_config_id,
        source_id="WTG_01",
        protocol=protocol,
        acquisition_mode=acquisition_mode,
        interval_ms=interval_ms,
        enabled=True,
    )


def _build_scheduler(
    runtime_configs: list[SourceRuntimeConfigData],
    *,
    use_case: FakeExecuteSourceAcquisitionUseCase | None = None,
    sub_use_case: FakeSubscribeSourceStateUseCase | None = None,
    plan_build: FakePlanBuildUseCase | None = None,
) -> SourceScheduler:
    uc = use_case or FakeExecuteSourceAcquisitionUseCase()
    sub = sub_use_case or FakeSubscribeSourceStateUseCase()
    pb = plan_build or FakePlanBuildUseCase()
    return SourceScheduler(
        runtime_config_port=FakeRuntimeConfigPort(runtime_configs),
        plan_build_usecase=cast(RuntimePlanBuildUseCase, pb),
        execute_source_acquisition_usecase_factory=lambda: cast(ExecuteSourceAcquisitionUseCase, uc),
        subscribe_source_state_usecase_factory=lambda: cast(SubscribeSourceStateUseCase, sub),
        settings=SchedulerSettings(scheduler_type="background"),
    )


def _get_start_callable(scheduler: SourceScheduler) -> Callable[[SourceRuntimeConfigData], None]:
    jobs = scheduler._scheduler.get_jobs()  # noqa: SLF001
    assert len(jobs) == 1
    return cast(Callable[[SourceRuntimeConfigData], None], jobs[0].func)


def test_reload_registers_runtime_job_with_runtime_config() -> None:
    """Keep the runtime config in runtime job state."""
    runtime_config = _build_runtime_config(101)
    scheduler = _build_scheduler([runtime_config])

    scheduler.reload()

    runtime_jobs = scheduler.get_runtime_jobs()
    assert len(runtime_jobs) == 1
    assert runtime_jobs[0].runtime_configs == (runtime_config,)
    assert runtime_jobs[0].aps_job_id == "once:101"
    assert runtime_jobs[0].status is JobStatus.SCHEDULED


def test_run_once_job_passes_plans_to_use_case() -> None:
    """Build plans from runtime config and dispatch to execute use case."""
    runtime_config = _build_runtime_config(101)
    pb = FakePlanBuildUseCase()
    use_case = FakeExecuteSourceAcquisitionUseCase()
    scheduler = _build_scheduler([runtime_config], use_case=use_case, plan_build=pb)
    scheduler.reload()

    job_func = _get_start_callable(scheduler)
    runtime_job = scheduler.get_runtime_jobs()[0]

    assert runtime_job.status is JobStatus.SCHEDULED

    job_func(
        cast(SourceRuntimeConfigData, scheduler._scheduler.get_jobs()[0].args[0])
    )  # noqa: SLF001

    assert runtime_job.status is JobStatus.RUNNING
    assert pb.captured_configs == [[runtime_config]]
    assert len(use_case.plan_batches) == 1


def test_run_once_job_marks_failed_result_as_failed_job() -> None:
    """Treat business FAILED results as failed scheduler jobs."""
    runtime_config = _build_runtime_config(101)
    use_case = FakeExecuteSourceAcquisitionUseCase(status=AcquisitionStatus.FAILED)
    scheduler = _build_scheduler([runtime_config], use_case=use_case)
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
    use_case = FakeExecuteSourceAcquisitionUseCase(status=AcquisitionStatus.EMPTY)
    scheduler = _build_scheduler([runtime_config], use_case=use_case)
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
    use_case = FakeExecuteSourceAcquisitionUseCase(status=AcquisitionStatus.DISABLED)
    scheduler = _build_scheduler([runtime_config], use_case=use_case)
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
    scheduler = _build_scheduler([first, second])

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
    scheduler = _build_scheduler([opcua_config, modbus_config])

    scheduler.reload()

    assert {job.aps_job_id for job in scheduler.get_runtime_jobs()} == {
        "polling:modbus:1000",
        "polling:opcua:1000",
    }


def test_polling_job_executes_merged_batch_with_one_use_case() -> None:
    """Dispatch same-interval polling configs as one plan batch."""
    first = _build_runtime_config(101, acquisition_mode="POLLING", interval_ms=1000)
    second = _build_runtime_config(102, acquisition_mode="POLLING", interval_ms=1000)
    pb = FakePlanBuildUseCase()
    use_case = FakeExecuteSourceAcquisitionUseCase()
    scheduler = _build_scheduler([first, second], use_case=use_case, plan_build=pb)
    scheduler.reload()

    job = scheduler._scheduler.get_jobs()[0]  # noqa: SLF001
    cast(Callable[[tuple[SourceRuntimeConfigData, ...]], None], job.func)(
        cast(tuple[SourceRuntimeConfigData, ...], job.args[0])
    )

    assert pb.captured_configs == [[first, second]]
    assert len(use_case.plan_batches) == 1


def test_subscription_job_sets_stop_event_on_stop() -> None:
    """Start subscription as one merged long-running job with a stop signal."""
    first = _build_runtime_config(101, acquisition_mode="SUBSCRIPTION")
    second = _build_runtime_config(102, acquisition_mode="SUBSCRIPTION")
    sub_use_case = FakeSubscribeSourceStateUseCase()
    scheduler = _build_scheduler([first, second], sub_use_case=sub_use_case)
    scheduler.reload()

    job = scheduler._scheduler.get_jobs()[0]  # noqa: SLF001
    cast(Callable[[tuple[SourceRuntimeConfigData, ...], object], None], job.func)(
        cast(tuple[SourceRuntimeConfigData, ...], job.args[0]),
        job.args[1],
    )
    scheduler.stop(wait=False)

    assert sub_use_case.calls[0][0] == (first, second)
    assert getattr(sub_use_case.calls[0][1], "is_set")()


def test_reload_splits_subscription_jobs_by_protocol() -> None:
    """Do not merge subscription configs from different protocols."""
    opcua_config = _build_runtime_config(101, acquisition_mode="SUBSCRIPTION")
    modbus_config = _build_runtime_config(
        102,
        protocol="modbus",
        acquisition_mode="SUBSCRIPTION",
    )
    scheduler = _build_scheduler([opcua_config, modbus_config])

    scheduler.reload()

    assert {job.aps_job_id for job in scheduler.get_runtime_jobs()} == {
        "subscription:modbus",
        "subscription:opcua",
    }
