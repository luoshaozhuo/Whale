"""SourceAcquisitionExecutionPlan — 预校验采集执行计划."""

from __future__ import annotations

from dataclasses import dataclass, field

from whale.ingest.usecases.dtos.acquisition_item_data import AcquisitionItemData
from whale.ingest.usecases.dtos.source_connection_data import SourceConnectionData


@dataclass(slots=True)
class SourceAcquisitionExecutionPlan:
    """预校验后的采集执行计划，ExecuteSourceAcquisitionUseCase 直接消费，无需再读 DB."""

    plan_id: str
    task_id: int
    ld_instance_id: int
    acquisition_mode: str
    protocol: str
    model_id: str | None = None
    endpoint_config: SourceConnectionData | None = None
    request_items: list[AcquisitionItemData] = field(default_factory=list)
    request_timeout_ms: int = 500
    freshness_timeout_ms: int = 30000
    alive_timeout_ms: int = 60000
    protocol_params: dict = field(default_factory=dict)
    trace_context: dict = field(default_factory=dict)
