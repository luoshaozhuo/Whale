"""Factory helpers for building APScheduler instances."""

from __future__ import annotations

from apscheduler.executors.pool import ProcessPoolExecutor, ThreadPoolExecutor
from apscheduler.jobstores.memory import MemoryJobStore
from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.schedulers.base import BaseScheduler
from apscheduler.schedulers.blocking import BlockingScheduler

from whale.ingest.runtime.scheduler_settings import SchedulerSettings


def build_scheduler(settings: SchedulerSettings) -> BaseScheduler:
    """Build one APScheduler instance from runtime settings."""
    scheduler_type = settings.scheduler_type.lower()
    scheduler_cls: type[BaseScheduler]

    if scheduler_type == "blocking":
        scheduler_cls = BlockingScheduler
    elif scheduler_type == "background":
        scheduler_cls = BackgroundScheduler
    else:
        raise ValueError(f"Unsupported scheduler_type: {settings.scheduler_type}")

    jobstores = {"default": _build_jobstore(settings)}
    executors = _build_executors(settings)
    job_defaults = {
        "coalesce": settings.job_defaults.coalesce,
        "max_instances": settings.job_defaults.max_instances,
        "misfire_grace_time": settings.job_defaults.misfire_grace_time,
    }

    return scheduler_cls(
        jobstores=jobstores,
        executors=executors,
        job_defaults=job_defaults,
        timezone=settings.timezone,
    )


def _build_jobstore(settings: SchedulerSettings) -> MemoryJobStore | SQLAlchemyJobStore:
    """Build the default APScheduler job store."""
    jobstore_type = settings.jobstore.type.lower()

    if jobstore_type == "memory":
        return MemoryJobStore()

    if jobstore_type == "sqlalchemy":
        if not settings.jobstore.url:
            raise ValueError("SQLAlchemy job store requires a non-empty url")
        return SQLAlchemyJobStore(url=settings.jobstore.url)

    raise ValueError(f"Unsupported jobstore type: {settings.jobstore.type}")


def _build_executors(
    settings: SchedulerSettings,
) -> dict[str, ThreadPoolExecutor | ProcessPoolExecutor]:
    """Build APScheduler executors."""
    executors: dict[str, ThreadPoolExecutor | ProcessPoolExecutor] = {
        "default": ThreadPoolExecutor(settings.executors.threadpool_max_workers),
    }

    if settings.executors.processpool_max_workers is not None:
        executors["processpool"] = ProcessPoolExecutor(
            settings.executors.processpool_max_workers,
        )

    return executors
