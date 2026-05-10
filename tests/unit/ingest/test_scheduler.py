"""Unit tests for the ingest runtime scheduler."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from typing import cast

from whale.ingest.runtime.job_status import JobStatus
from whale.ingest.runtime.scheduler import SourceScheduler
from whale.ingest.runtime.scheduler_settings import SchedulerSettings
from whale.ingest.usecases.build_runtime_plan_usecase import RuntimePlanBuildUseCase
from whale.ingest.usecases.dtos.acquisition_execution_options import (
    AcquisitionExecutionOptions,
)
from whale.ingest.usecases.dtos.acquisition_status import AcquisitionStatus
from whale.ingest.usecases.dtos.source_acquisition_request import SourceAcquisitionRequest
from whale.ingest.usecases.dtos.source_connection_data import SourceConnectionData
from whale.ingest.usecases.dtos.source_runtime_config_data import (
    SourceRuntimeConfigData,
)
from whale.ingest.usecases.dtos.source_state_acquisition_result import (
    SourceStateAcquisitionResult,
)
from whale.ingest.usecases.polling_acquisition_usecase import PollingAcquisitionUseCase
from whale.ingest.usecases.subscribe_acquisition_usecase import (
    SubscribeAcquisitionUseCase,
)


class FakeRuntimeConfigPort:
    def __init__(self, configs: list[SourceRuntimeConfigData]) -> None:
        self._configs = list(configs)

    def list_enabled(self) -> list[SourceRuntimeConfigData]:
        return list(self._configs)


class FakePlanBuildUseCase:
    def __init__(self) -> None:
        self.captured_configs: list[list[SourceRuntimeConfigData]] = []

    def build_requests(self, configs: list[SourceRuntimeConfigData]) -> list[SourceAcquisitionRequest]:
        self.captured_configs.append(list(configs))
        return [
            SourceAcquisitionRequest(
                request_id=f"task-{cfg.runtime_config_id}",
                task_id=cfg.runtime_config_id,
                execution=AcquisitionExecutionOptions(
                    protocol=cfg.protocol,
                    transport="tcp",
                    acquisition_mode=cfg.acquisition_mode,
                    interval_ms=cfg.interval_ms,
                    max_iteration=None,
                    request_timeout_ms=500,
                    freshness_timeout_ms=30000,
                    alive_timeout_ms=60000,
                ),
                connections=[
                    SourceConnectionData(
                        host="127.0.0.1",
                        port=4840,
                        ied_name=f"IED_{cfg.source_id}",
                        ld_name=cfg.source_id,
                        namespace_uri="urn:windfarm:2wtg",
                    )
                ],
                items=[],
            )
            for cfg in configs
        ]


class FakePollingAcquisitionUseCase:
    def __init__(
        self,
        status: AcquisitionStatus = AcquisitionStatus.SUCCEEDED,
    ) -> None:
        self._status = status
        self.request_batches: list[SourceAcquisitionRequest] = []

    async def execute_once(
        self,
        request: SourceAcquisitionRequest,
    ) -> list[SourceStateAcquisitionResult]:
        self.request_batches.append(request)
        return [
            SourceStateAcquisitionResult(
                plan_id=request.request_id,
                task_id=request.task_id,
                ld_instance_id=0,
                status=self._status,
                started_at=(now := datetime.now(tz=UTC)),
                ended_at=now,
                error_message=None if self._status is not AcquisitionStatus.FAILED else "boom",
            )
        ]

    async def execute(
        self,
        request: SourceAcquisitionRequest,
        stop_event: object,
    ) -> None:
        self.request_batches.append(request)
        getattr(stop_event, "set", lambda: None)()


class FakeSubscribeAcquisitionUseCase:
    def __init__(self) -> None:
        self.calls: list[tuple[SourceAcquisitionRequest, object]] = []

    async def execute(
        self,
        request: SourceAcquisitionRequest,
        stop_event: object,
    ) -> None:
        self.calls.append((request, stop_event))


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
    use_case: FakePollingAcquisitionUseCase | None = None,
    sub_use_case: FakeSubscribeAcquisitionUseCase | None = None,
    plan_build: FakePlanBuildUseCase | None = None,
) -> SourceScheduler:
    uc = use_case or FakePollingAcquisitionUseCase()
    sub = sub_use_case or FakeSubscribeAcquisitionUseCase()
    pb = plan_build or FakePlanBuildUseCase()
    return SourceScheduler(
        runtime_config_port=FakeRuntimeConfigPort(runtime_configs),
        plan_build_usecase=cast(RuntimePlanBuildUseCase, pb),
        polling_acquisition_usecase_factory=lambda: cast(PollingAcquisitionUseCase, uc),
        subscribe_acquisition_usecase_factory=lambda: cast(SubscribeAcquisitionUseCase, sub),
        settings=SchedulerSettings(scheduler_type="background"),
    )


def _get_start_callable(scheduler: SourceScheduler) -> Callable[..., None]:
    jobs = scheduler._scheduler.get_jobs()  # noqa: SLF001
    assert len(jobs) == 1
    return cast(Callable[..., None], jobs[0].func)


def test_reload_registers_runtime_job_with_runtime_config() -> None:
    runtime_config = _build_runtime_config(101)
    scheduler = _build_scheduler([runtime_config])

    scheduler.reload()

    runtime_jobs = scheduler.get_runtime_jobs()
    assert len(runtime_jobs) == 1
    assert runtime_jobs[0].runtime_configs == (runtime_config,)
    assert runtime_jobs[0].aps_job_id == "once:101"
    assert runtime_jobs[0].status is JobStatus.SCHEDULED


def test_run_once_job_passes_requests_to_use_case() -> None:
    runtime_config = _build_runtime_config(101)
    pb = FakePlanBuildUseCase()
    use_case = FakePollingAcquisitionUseCase()
    scheduler = _build_scheduler([runtime_config], use_case=use_case, plan_build=pb)
    scheduler.reload()

    job_func = _get_start_callable(scheduler)
    runtime_job = scheduler.get_runtime_jobs()[0]

    assert runtime_job.status is JobStatus.SCHEDULED

    job_func(cast(SourceRuntimeConfigData, scheduler._scheduler.get_jobs()[0].args[0]))  # noqa: SLF001

    assert runtime_job.status is JobStatus.RUNNING
    assert pb.captured_configs == [[runtime_config]]
    assert len(use_case.request_batches) == 1
    assert use_case.request_batches[0].execution.max_iteration == 1


def test_run_once_job_marks_failed_result_as_failed_job() -> None:
    runtime_config = _build_runtime_config(101)
    use_case = FakePollingAcquisitionUseCase(status=AcquisitionStatus.FAILED)
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
    runtime_config = _build_runtime_config(101)
    use_case = FakePollingAcquisitionUseCase(status=AcquisitionStatus.EMPTY)
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
    runtime_config = _build_runtime_config(101)
    use_case = FakePollingAcquisitionUseCase(status=AcquisitionStatus.DISABLED)
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


def test_reload_merges_polling_jobs_by_protocol() -> None:
    first = _build_runtime_config(101, acquisition_mode="POLLING", interval_ms=1000)
    second = _build_runtime_config(102, acquisition_mode="POLLING", interval_ms=2000)
    scheduler = _build_scheduler([first, second])

    scheduler.reload()

    runtime_jobs = scheduler.get_runtime_jobs()
    assert len(runtime_jobs) == 1
    assert runtime_jobs[0].aps_job_id == "polling:opcua"
    assert runtime_jobs[0].runtime_configs == (first, second)


def test_reload_splits_polling_jobs_by_protocol() -> None:
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
        "polling:modbus",
        "polling:opcua",
    }


def test_polling_job_dispatches_request_batch_with_one_use_case() -> None:
    first = _build_runtime_config(101, acquisition_mode="POLLING", interval_ms=1000)
    second = _build_runtime_config(102, acquisition_mode="POLLING", interval_ms=1000)
    pb = FakePlanBuildUseCase()
    use_case = FakePollingAcquisitionUseCase()
    scheduler = _build_scheduler([first, second], use_case=use_case, plan_build=pb)
    scheduler.reload()

    job = scheduler._scheduler.get_jobs()[0]  # noqa: SLF001
    cast(Callable[[tuple[SourceRuntimeConfigData, ...], object], None], job.func)(
        cast(tuple[SourceRuntimeConfigData, ...], job.args[0]),
        job.args[1],
    )

    assert pb.captured_configs == [[first, second]]
    assert len(use_case.request_batches) == 2
    assert [request.task_id for request in use_case.request_batches] == [101, 102]


def test_subscription_job_sets_stop_event_on_stop() -> None:
    first = _build_runtime_config(101, acquisition_mode="SUBSCRIPTION")
    second = _build_runtime_config(102, acquisition_mode="SUBSCRIPTION")
    sub_use_case = FakeSubscribeAcquisitionUseCase()
    scheduler = _build_scheduler([first, second], sub_use_case=sub_use_case)
    scheduler.reload()

    job = scheduler._scheduler.get_jobs()[0]  # noqa: SLF001
    cast(Callable[[tuple[SourceRuntimeConfigData, ...], object], None], job.func)(
        cast(tuple[SourceRuntimeConfigData, ...], job.args[0]),
        job.args[1],
    )
    scheduler.stop(wait=False)

    assert [request.task_id for request, _ in sub_use_case.calls] == [101, 102]
    assert all(getattr(stop_event, "is_set")() for _, stop_event in sub_use_case.calls)


def test_reload_splits_subscription_jobs_by_protocol() -> None:
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
