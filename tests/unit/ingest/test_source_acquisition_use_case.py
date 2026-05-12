"""Unit tests for the active source-acquisition use case."""

from __future__ import annotations

import asyncio
import importlib.util
from pathlib import Path

import pytest

from whale.ingest.usecases.dtos.source_acquisition_request import (
    AcquisitionExecutionOptions,
    AcquisitionItemData,
    SourceAcquisitionRequest,
)
from whale.ingest.usecases.dtos.source_acquisition_start_result import (
    SourceAcquisitionStartResult,
)
from whale.ingest.usecases.dtos.source_connection_data import SourceConnectionData


_MODULE_PATH = (
    Path(__file__).resolve().parents[3]
    / "src/whale/ingest/usecases/SourceAcquisitionUseCase .py"
)
_SPEC = importlib.util.spec_from_file_location("whale.ingest.usecases.source_acquisition_use_case", _MODULE_PATH)
assert _SPEC is not None
assert _SPEC.loader is not None
_MODULE = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_MODULE)
SourceAcquisitionUseCase = _MODULE.SourceAcquisitionUseCase


class FakePollingRole:
    def __init__(self) -> None:
        self.calls: list[SourceAcquisitionRequest] = []

    def start(self, request: SourceAcquisitionRequest) -> SourceAcquisitionStartResult:
        self.calls.append(request)
        return SourceAcquisitionStartResult(
            request_id=request.request_id,
            task_id=request.task_id,
            mode="POLLING",
            sessions=[],
        )


class FakeSubscriptionRole:
    def __init__(self) -> None:
        self.calls: list[SourceAcquisitionRequest] = []

    async def start(
        self,
        request: SourceAcquisitionRequest,
    ) -> SourceAcquisitionStartResult:
        self.calls.append(request)
        return SourceAcquisitionStartResult(
            request_id=request.request_id,
            task_id=request.task_id,
            mode="SUBSCRIBE",
            sessions=[],
        )


def _build_request(acquisition_mode: str) -> SourceAcquisitionRequest:
    return SourceAcquisitionRequest(
        request_id="request-1",
        task_id=101,
        execution=AcquisitionExecutionOptions(
            protocol="opcua",
            transport="tcp",
            acquisition_mode=acquisition_mode,
            interval_ms=100,
            max_iteration=1 if acquisition_mode != "SUBSCRIBE" else None,
            request_timeout_ms=500,
            freshness_timeout_ms=30000,
            alive_timeout_ms=60000,
        ),
        connections=[
            SourceConnectionData(
                host="127.0.0.1",
                port=4840,
                ied_name="IED_01",
                ld_name="LD_01",
                namespace_uri="urn:test",
            )
        ],
        items=[AcquisitionItemData(key="TotW", profile_item_id=1, relative_path="TotW")],
    )


def test_start_routes_polling_modes_to_polling_role() -> None:
    polling_role = FakePollingRole()
    subscription_role = FakeSubscriptionRole()
    use_case = SourceAcquisitionUseCase(
        polling_role=polling_role,
        subscription_role=subscription_role,
    )

    result = asyncio.run(use_case.start(_build_request("READ_ONCE")))

    assert result.mode == "POLLING"
    assert len(polling_role.calls) == 1
    assert subscription_role.calls == []


def test_start_routes_subscription_modes_to_subscription_role() -> None:
    polling_role = FakePollingRole()
    subscription_role = FakeSubscriptionRole()
    use_case = SourceAcquisitionUseCase(
        polling_role=polling_role,
        subscription_role=subscription_role,
    )

    result = asyncio.run(use_case.start(_build_request("SUBSCRIBE")))

    assert result.mode == "SUBSCRIBE"
    assert polling_role.calls == []
    assert len(subscription_role.calls) == 1


def test_start_validates_non_empty_items() -> None:
    polling_role = FakePollingRole()
    subscription_role = FakeSubscriptionRole()
    use_case = SourceAcquisitionUseCase(
        polling_role=polling_role,
        subscription_role=subscription_role,
    )
    request = _build_request("POLLING")
    request.items = []

    with pytest.raises(ValueError, match="items cannot be empty"):
        asyncio.run(use_case.start(request))
