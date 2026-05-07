"""SourceStateReadRole — 基于 ExecutionPlan 调 adapter 读取 source."""

from __future__ import annotations

from whale.ingest.ports.source.source_acquisition_port import SourceAcquisitionPort
from whale.ingest.usecases.dtos.acquisition_status import AcquisitionStatus
from whale.ingest.usecases.dtos.source_acquisition_execution_plan import (
    SourceAcquisitionExecutionPlan,
)
from whale.ingest.usecases.dtos.source_acquisition_request import (
    SourceAcquisitionRequest,
)
from whale.ingest.usecases.dtos.source_connection_data import SourceConnectionData
from whale.ingest.usecases.dtos.source_state_data import SourceStateData


class SourceStateReadRole:
    """只负责基于 SourceAcquisitionExecutionPlan 调 adapter 读取 source.

    不处理周期，不读数据库配置，不写 Redis，不写诊断表。
    """

    def __init__(self, acquisition_port: SourceAcquisitionPort) -> None:
        self._acquisition_port = acquisition_port

    async def acquire(self, plan: SourceAcquisitionExecutionPlan) -> SourceStateData:
        try:
            request = self._build_request(plan)
            states = await self._acquisition_port.read(request)
        except Exception as exc:
            return SourceStateData(
                runtime_config_id=plan.task_id,
                acquisition_status=AcquisitionStatus.FAILED,
                model_id=plan.model_id,
                last_error=str(exc),
            )

        return SourceStateData(
            runtime_config_id=plan.task_id,
            acquisition_status=(
                AcquisitionStatus.SUCCEEDED if states else AcquisitionStatus.EMPTY
            ),
            model_id=plan.model_id,
            acquired_states=states,
        )

    @staticmethod
    def _build_request(plan: SourceAcquisitionExecutionPlan) -> SourceAcquisitionRequest:
        endpoint = plan.endpoint_config
        ns_uri = endpoint.params.get("namespace_uri", "") if endpoint else ""
        return SourceAcquisitionRequest(
            source_id=str(plan.task_id),
            connection=endpoint or SourceConnectionData(),
            items=list(plan.request_items),
            resolved_endpoint=endpoint.endpoint if endpoint else None,
            request_timeout_ms=plan.request_timeout_ms,
            resolved_node_ids=[
                f"nsu={ns_uri};s={item.locator}"
                if ns_uri and not item.locator.startswith(("ns=", "nsu="))
                else item.locator
                for item in plan.request_items
            ],
        )
