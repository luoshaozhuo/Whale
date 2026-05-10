"""Unit tests for the runtime-plan build use case."""

from __future__ import annotations

import pytest

from whale.ingest.usecases.build_runtime_plan_usecase import RuntimePlanBuildUseCase
from whale.ingest.usecases.dtos.acquisition_execution_options import (
    AcquisitionExecutionOptions,
)
from whale.ingest.usecases.dtos.acquisition_item_data import AcquisitionItemData
from whale.ingest.usecases.dtos.source_acquisition_definition import (
    SourceAcquisitionDefinition,
)
from whale.ingest.usecases.dtos.source_connection_data import SourceConnectionData
from whale.ingest.usecases.dtos.source_runtime_config_data import (
    SourceRuntimeConfigData,
)


class FakeRuntimeConfigPort:
    def list_enabled(self) -> list[SourceRuntimeConfigData]:
        return []


class FakeDefinitionPort:
    def __init__(
        self,
        *,
        request_timeout_ms: int = 1200,
        poll_interval_ms: int = 2000,
    ) -> None:
        self._request_timeout_ms = request_timeout_ms
        self._poll_interval_ms = poll_interval_ms

    def get_config(
        self,
        runtime_config: SourceRuntimeConfigData,
    ) -> SourceAcquisitionDefinition:
        del runtime_config
        return SourceAcquisitionDefinition(
            ld_id="goldwind_gw121_opcua",
            connection=SourceConnectionData(
                host="127.0.0.1",
                port=4840,
                ied_name="IED_WTG_01",
                ld_name="WTG_01",
                namespace_uri="urn:windfarm:2wtg",
            ),
            items=[
                AcquisitionItemData(
                    key="TotW",
                    profile_item_id=1,
                    relative_path="WTG_01.TotW",
                )
            ],
            request_timeout_ms=self._request_timeout_ms,
            poll_interval_ms=self._poll_interval_ms,
        )


def test_build_requests_carries_connection_and_items_into_request() -> None:
    """把定义层的连接和点位信息原样带入执行请求。"""
    runtime_config = SourceRuntimeConfigData(
        runtime_config_id=101,
        source_id="WTG_01",
        protocol="opcua",
        acquisition_mode="READ_ONCE",
        interval_ms=0,
        enabled=True,
    )
    use_case = RuntimePlanBuildUseCase(
        runtime_config_port=FakeRuntimeConfigPort(),
        acquisition_definition_port=FakeDefinitionPort(
            request_timeout_ms=1200,
            poll_interval_ms=100,
        ),
    )

    request = use_case.build_requests([runtime_config])[0]

    assert request.task_id == 101
    assert request.execution.transport == "tcp"
    assert request.execution.max_iteration == 1
    assert request.execution.request_timeout_ms == 1200
    assert request.connections[0].ld_name == "WTG_01"
    assert request.items[0].key == "TotW"

def test_build_requests_rejects_polling_when_timeout_reaches_interval() -> None:
    """Keep interval validation for repeated polling requests."""
    runtime_config = SourceRuntimeConfigData(
        runtime_config_id=102,
        source_id="WTG_02",
        protocol="opcua",
        acquisition_mode="POLLING",
        interval_ms=1000,
        enabled=True,
    )
    use_case = RuntimePlanBuildUseCase(
        runtime_config_port=FakeRuntimeConfigPort(),
        acquisition_definition_port=FakeDefinitionPort(
            request_timeout_ms=1200,
            poll_interval_ms=1000,
        ),
    )

    with pytest.raises(RuntimeError, match="request_timeout_ms"):
        use_case.build_requests([runtime_config])
