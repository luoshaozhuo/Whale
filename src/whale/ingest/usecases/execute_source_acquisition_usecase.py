"""ExecuteSourceAcquisitionUseCase — 执行已准备好的采集计划."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime

from whale.ingest.ports.source.source_acquisition_port_registry import (
    SourceAcquisitionPortRegistry,
)
from whale.ingest.ports.state import SourceStateCachePort
from whale.ingest.usecases.dtos.acquisition_status import AcquisitionStatus
from whale.ingest.usecases.dtos.source_acquisition_execution_plan import (
    SourceAcquisitionExecutionPlan,
)
from whale.ingest.usecases.dtos.source_state_acquisition_result import (
    SourceStateAcquisitionResult,
)
from whale.ingest.usecases.roles.runtime_diagnostics_role import (
    RuntimeDiagnosticsRole,
)
from whale.ingest.usecases.roles.source_state_read_role import SourceStateReadRole
from whale.ingest.usecases.roles.state_update_role import StateUpdateRole


class ExecuteSourceAcquisitionUseCase:
    """只执行“一轮已准备好的采集任务”，不读数据库配置，不做 runtime plan 构建，不管理周期，不发布 Kafka."""

    def __init__(
        self,
        acquisition_port_registry: SourceAcquisitionPortRegistry,
        state_cache_port: SourceStateCachePort,
        diagnostics_role: RuntimeDiagnosticsRole | None = None,
        max_in_flight: int = 8,
    ) -> None:
        if max_in_flight <= 0:
            raise ValueError("max_in_flight must be greater than 0")
        self._acquisition_port_registry = acquisition_port_registry
        self._update_role = StateUpdateRole(state_cache_port=state_cache_port)
        self._diagnostics_role = diagnostics_role
        self._max_in_flight = max_in_flight

    async def execute(
        self,
        plans: list[SourceAcquisitionExecutionPlan],
    ) -> list[SourceStateAcquisitionResult]:
        """Execute one batch of pre-built acquisition plans with bounded device concurrency."""
        if not plans:
            return []

        semaphore = asyncio.Semaphore(self._max_in_flight)
        tasks = [
            asyncio.create_task(self._execute_plan(plan, semaphore))
            for plan in plans
        ]
        return list(await asyncio.gather(*tasks))

    async def _execute_plan(
        self,
        plan: SourceAcquisitionExecutionPlan,
        semaphore: asyncio.Semaphore,
    ) -> SourceStateAcquisitionResult:
        async with semaphore:
            started_at = datetime.now(tz=UTC)
            read_role = SourceStateReadRole(
                acquisition_port=self._acquisition_port_registry.get(plan.protocol),
            )
            data = await read_role.acquire(plan)

            if data.acquisition_status is AcquisitionStatus.SUCCEEDED:
                try:
                    self._update_role.apply_for_mode(data, plan.acquisition_mode)
                except Exception:
                    return self._build_result(
                        plan, started_at, AcquisitionStatus.FAILED,
                        failure_category="CACHE_UPDATE_FAILED",
                        error_code="REDIS_WRITE_TIMEOUT",
                        error_message="latest-state cache update failed",
                    )

            if self._diagnostics_role is not None:
                if data.acquisition_status is AcquisitionStatus.SUCCEEDED:
                    self._diagnostics_role.record_success(
                        plan.task_id, plan.ld_instance_id, plan.acquisition_mode,
                    )
                elif data.last_error:
                    self._diagnostics_role.record_failure(
                        plan.task_id, plan.ld_instance_id, plan.acquisition_mode,
                        Exception(data.last_error), protocol=plan.protocol,
                    )

            return self._build_result(
                plan, started_at, data.acquisition_status, error_message=data.last_error,
            )

    @staticmethod
    def _build_result(
        plan: SourceAcquisitionExecutionPlan,
        started_at: datetime,
        status: AcquisitionStatus,
        failure_category: str | None = None,
        error_code: str | None = None,
        error_message: str | None = None,
    ) -> SourceStateAcquisitionResult:
        ended_at = datetime.now(tz=UTC)
        elapsed_ms = (ended_at - started_at).total_seconds() * 1000
        return SourceStateAcquisitionResult(
            plan_id=plan.plan_id,
            task_id=plan.task_id,
            ld_instance_id=plan.ld_instance_id,
            status=status,
            started_at=started_at,
            ended_at=ended_at,
            elapsed_ms=elapsed_ms,
            failure_category=failure_category,
            error_code=error_code,
            error_message=error_message,
            expected_item_count=len(plan.request_items),
            actual_item_count=0,
            bad_item_count=0,
        )
