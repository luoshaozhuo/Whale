"""Runtime scheduler for ingest.

Current stage:
- focus on ONCE mode first
- use APScheduler as the scheduling backend
- scheduler reads enabled runtime configs and dispatches jobs
- POLLING and SUBSCRIPTION keep explicit extension points
"""

from __future__ import annotations

import time
from typing import Any

from apscheduler.events import (  # type: ignore[import-untyped]
    EVENT_JOB_ERROR,
    EVENT_JOB_EXECUTED,
    JobExecutionEvent,
)
from apscheduler.schedulers.base import BaseScheduler  # type: ignore[import-untyped]

from whale.ingest.ports.runtime.source_runtime_config_port import SourceRuntimeConfigPort
from whale.ingest.runtime.acquisition_mode import AcquisitionMode
from whale.ingest.runtime.job_status import JobStatus
from whale.ingest.runtime.scheduler_factory import build_scheduler
from whale.ingest.runtime.scheduler_job import ScheduledSourceJob
from whale.ingest.runtime.scheduler_settings import SchedulerSettings
from whale.ingest.usecases.dtos.acquisition_status import AcquisitionStatus
from whale.ingest.usecases.dtos.refresh_source_state_command import (
    RefreshSourceStateCommand,
)
from whale.ingest.usecases.dtos.source_runtime_config_data import (
    SourceRuntimeConfigData,
)
from whale.ingest.usecases.refresh_source_state_usecase import (
    RefreshSourceStateUseCase,
)


class SourceScheduler:
    """Drive ingest use cases from runtime configurations."""

    def __init__(
        self,
        runtime_config_port: SourceRuntimeConfigPort,
        refresh_source_state_usecase: RefreshSourceStateUseCase,
        settings: SchedulerSettings | None = None,
    ) -> None:
        """Initialize the scheduler with required dependencies."""
        self._runtime_config_port = runtime_config_port
        self._refresh_source_state_usecase = refresh_source_state_usecase
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

    def wait_until_terminal(self, timeout_seconds: float) -> bool:
        """Wait until all registered jobs reach terminal states."""
        deadline = time.monotonic() + timeout_seconds
        terminal_statuses = {JobStatus.FINISHED, JobStatus.FAILED, JobStatus.STOPPED}

        while time.monotonic() < deadline:
            if all(job.status in terminal_statuses for job in self._jobs.values()):
                return True
            time.sleep(0.05)

        return all(job.status in terminal_statuses for job in self._jobs.values())

    def has_failures(self) -> bool:
        """Return whether any registered job failed."""
        return any(
            job.status is JobStatus.FAILED
            or (job.last_result is not None and job.last_result.status is AcquisitionStatus.FAILED)
            for job in self._jobs.values()
        )

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
        """Register jobs from enabled runtime configs."""
        runtime_configs = self._runtime_config_port.list_enabled()

        for runtime_config in runtime_configs:
            mode = self._get_acquisition_mode(runtime_config)

            if mode is AcquisitionMode.ONCE:
                self._register_once_job(runtime_config)
            elif mode is AcquisitionMode.POLLING:
                pass
                # self._register_polling_job(runtime_config)
            elif mode is AcquisitionMode.SUBSCRIPTION:
                pass
                # self._register_subscription_job(runtime_config)
            else:
                raise ValueError(f"Unsupported acquisition mode: {mode}")

    def _register_once_job(self, runtime_config: SourceRuntimeConfigData) -> None:
        """Register one immediate ONCE job."""
        runtime_config_id = runtime_config.runtime_config_id
        job_id = self._build_once_job_id(runtime_config_id)

        if job_id in self._jobs:
            return

        self._scheduler.add_job(
            self._run_once_job,
            id=job_id,
            replace_existing=False,
            args=[runtime_config_id],
        )

        self._jobs[job_id] = ScheduledSourceJob(
            runtime_config=runtime_config,
            aps_job_id=job_id,
            status=JobStatus.SCHEDULED,
        )

    def _register_polling_job(self, runtime_config: Any) -> None:
        """Register one polling job.

        Current stage keeps the branch explicit but unimplemented.
        """
        del runtime_config
        raise NotImplementedError("POLLING mode is not implemented yet")

    def _register_subscription_job(self, runtime_config: Any) -> None:
        """Register one subscription job.

        Current stage keeps the branch explicit but unimplemented.
        """
        del runtime_config
        raise NotImplementedError("SUBSCRIPTION mode is not implemented yet")

    def _run_once_job(self, runtime_config_id: int) -> None:
        """Execute one ONCE job."""
        job_id = self._build_once_job_id(runtime_config_id)
        runtime_job = self._jobs.get(job_id)

        if runtime_job is not None:
            runtime_job.status = JobStatus.RUNNING

        result = self._refresh_source_state_usecase.execute(
            RefreshSourceStateCommand(runtime_config_id=runtime_config_id)
        )
        if runtime_job is not None:
            runtime_job.last_result = result
            if result.status is AcquisitionStatus.FAILED:
                runtime_job.status = JobStatus.FAILED

    def _on_job_executed_or_failed(self, event: JobExecutionEvent) -> None:
        """Handle APScheduler job completion events."""
        runtime_job = self._jobs.get(event.job_id)
        if runtime_job is None:
            return

        if event.exception is None and runtime_job.status is not JobStatus.FAILED:
            runtime_job.status = JobStatus.FINISHED
        else:
            runtime_job.status = JobStatus.FAILED

    def _clear_registered_jobs(self) -> None:
        """Remove all APScheduler jobs and clear runtime registry."""
        for aps_job in self._scheduler.get_jobs():
            aps_job.remove()
        self._jobs.clear()

    @staticmethod
    def _build_once_job_id(runtime_config_id: int) -> str:
        """Build one stable job identifier for ONCE mode."""
        return f"once:{runtime_config_id}"

    @staticmethod
    def _get_acquisition_mode(runtime_config: SourceRuntimeConfigData) -> AcquisitionMode:
        """Extract acquisition mode from one runtime config."""
        try:
            return AcquisitionMode(runtime_config.acquisition_mode.upper())
        except ValueError as exc:
            raise ValueError(
                f"Unsupported acquisition mode: {runtime_config.acquisition_mode}"
            ) from exc
