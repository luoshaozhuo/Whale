"""Runtime scheduler for ingest.

Current stage:
- focus on ONCE mode first
- use APScheduler as the scheduling backend
- scheduler reads enabled execution plans and dispatches jobs
- POLLING and SUBSCRIPTION keep explicit extension points
"""

from __future__ import annotations

from typing import Any

from apscheduler.events import EVENT_JOB_ERROR, EVENT_JOB_EXECUTED, JobExecutionEvent
from apscheduler.schedulers.base import BaseScheduler

from whale.ingest.ports.source.source_execution_plan_port import SourceExecutionPlanPort
from whale.ingest.runtime.acquisition_mode import AcquisitionMode
from whale.ingest.runtime.job_status import JobStatus
from whale.ingest.runtime.scheduler_factory import build_scheduler
from whale.ingest.runtime.scheduler_job import ScheduledSourceJob
from whale.ingest.runtime.scheduler_settings import SchedulerSettings
from whale.ingest.usecases.dtos.maintain_source_state_command import (
    MaintainSourceStateCommand,
)
from whale.ingest.usecases.maintain_source_state_usecase import (
    MaintainSourceStateUseCase,
)


class SourceScheduler:
    """Drive ingest use cases from execution plans."""

    def __init__(
        self,
        execution_plan_port: SourceExecutionPlanPort,
        maintain_source_state_usecase: MaintainSourceStateUseCase,
        settings: SchedulerSettings | None = None,
    ) -> None:
        """Initialize the scheduler with required dependencies."""
        self._execution_plan_port = execution_plan_port
        self._maintain_source_state_usecase = maintain_source_state_usecase
        self._settings = settings or SchedulerSettings()
        self._scheduler: BaseScheduler = build_scheduler(self._settings)
        self._jobs: dict[str, ScheduledSourceJob] = {}

        self._scheduler.add_listener(
            self._on_job_executed_or_failed,
            EVENT_JOB_EXECUTED | EVENT_JOB_ERROR,
        )

    def run(self) -> None:
        """Load enabled execution plans and start the scheduler."""
        self.reload()
        self._scheduler.start()

    def stop(self, wait: bool = True) -> None:
        """Shutdown the scheduler and mark all runtime jobs as stopped."""
        for runtime_job in self._jobs.values():
            if runtime_job.status in {JobStatus.SCHEDULED, JobStatus.RUNNING}:
                runtime_job.status = JobStatus.STOPPED

        if self._scheduler.running:
            self._scheduler.shutdown(wait=wait)

    def reload(self) -> None:
        """Reload enabled execution plans and register jobs again."""
        self._clear_registered_jobs()
        self._register_jobs()

    def get_runtime_jobs(self) -> list[ScheduledSourceJob]:
        """Return in-memory runtime jobs."""
        return list(self._jobs.values())

    def _register_jobs(self) -> None:
        """Register jobs from enabled execution plans."""
        plans = self._execution_plan_port.get_enabled_execution_plans()

        for plan in plans:
            mode = self._get_acquisition_mode(plan)

            if mode is AcquisitionMode.ONCE:
                self._register_once_job(plan)
            elif mode is AcquisitionMode.POLLING:
                self._register_polling_job(plan)
            elif mode is AcquisitionMode.SUBSCRIPTION:
                self._register_subscription_job(plan)
            else:
                raise ValueError(f"Unsupported acquisition mode: {mode}")

    def _register_once_job(self, plan: Any) -> None:
        """Register one immediate ONCE job."""
        source_id = self._get_source_id(plan)
        job_id = self._build_once_job_id(source_id)

        if job_id in self._jobs:
            return

        self._scheduler.add_job(
            self._run_once_job,
            id=job_id,
            replace_existing=False,
            args=[source_id],
        )

        self._jobs[job_id] = ScheduledSourceJob(
            source_id=source_id,
            mode=AcquisitionMode.ONCE,
            aps_job_id=job_id,
            status=JobStatus.SCHEDULED,
        )

    def _register_polling_job(self, plan: Any) -> None:
        """Register one polling job.

        Current stage keeps the branch explicit but unimplemented.
        """
        raise NotImplementedError("POLLING mode is not implemented yet")

    def _register_subscription_job(self, plan: Any) -> None:
        """Register one subscription job.

        Current stage keeps the branch explicit but unimplemented.
        """
        raise NotImplementedError("SUBSCRIPTION mode is not implemented yet")

    def _run_once_job(self, source_id: str) -> None:
        """Execute one ONCE job."""
        job_id = self._build_once_job_id(source_id)
        runtime_job = self._jobs.get(job_id)

        if runtime_job is not None:
            runtime_job.status = JobStatus.RUNNING

        command = MaintainSourceStateCommand(source_id=source_id)
        self._maintain_source_state_usecase.execute(command)

    def _on_job_executed_or_failed(self, event: JobExecutionEvent) -> None:
        """Handle APScheduler job completion events."""
        runtime_job = self._jobs.get(event.job_id)
        if runtime_job is None:
            return

        if event.exception is None:
            runtime_job.status = JobStatus.FINISHED
        else:
            runtime_job.status = JobStatus.FAILED

    def _clear_registered_jobs(self) -> None:
        """Remove all APScheduler jobs and clear runtime registry."""
        for aps_job in self._scheduler.get_jobs():
            aps_job.remove()
        self._jobs.clear()

    @staticmethod
    def _build_once_job_id(source_id: str) -> str:
        """Build one stable job identifier for ONCE mode."""
        return f"once:{source_id}"

    @staticmethod
    def _get_source_id(plan: Any) -> str:
        """Extract source_id from one execution plan."""
        source_id = getattr(plan, "source_id", None)
        if not isinstance(source_id, str) or not source_id.strip():
            raise ValueError("Execution plan missing valid source_id")
        return source_id.strip()

    @staticmethod
    def _get_acquisition_mode(plan: Any) -> AcquisitionMode:
        """Extract acquisition mode from one execution plan."""
        mode = getattr(plan, "acquisition_mode", None)
        if mode is None:
            schedule_spec = getattr(plan, "schedule_spec", None)
            mode = getattr(schedule_spec, "acquisition_mode", None)

        if not isinstance(mode, str):
            raise ValueError("Execution plan missing valid acquisition_mode")

        try:
            return AcquisitionMode(mode.upper())
        except ValueError as exc:
            raise ValueError(f"Unsupported acquisition mode: {mode}") from exc
