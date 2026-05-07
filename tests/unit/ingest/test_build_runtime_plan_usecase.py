"""Unit tests for the runtime-plan build use case."""

from __future__ import annotations

import pytest

from whale.ingest.usecases.build_runtime_plan_usecase import RuntimePlanBuildUseCase
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
            connection=SourceConnectionData(endpoint="opc.tcp://127.0.0.1:4840"),
            items=[AcquisitionItemData(key="TotW", locator="ns=2;s=WTG_01.TotW")],
            request_timeout_ms=self._request_timeout_ms,
            poll_interval_ms=self._poll_interval_ms,
        )


def test_build_plans_carries_ld_id_into_model_id() -> None:
    """Populate model_id from the acquisition definition for cache updates."""
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

    plan = use_case.build_plans([runtime_config])[0]

    assert plan.task_id == 101
    assert plan.model_id == "goldwind_gw121_opcua"
    assert plan.request_timeout_ms == 1200
    assert plan.request_items[0].key == "TotW"


def test_build_plans_rejects_polling_when_timeout_reaches_interval() -> None:
    """Keep interval validation for repeated polling plans."""
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
        use_case.build_plans([runtime_config])
