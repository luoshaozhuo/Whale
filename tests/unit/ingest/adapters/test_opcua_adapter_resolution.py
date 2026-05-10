"""Unit tests for OpcUaSourceAcquisitionAdapter endpoint / node ID resolution."""

from __future__ import annotations

from whale.ingest.adapters.source.opcua_source_acquisition_adapter import (
    OpcUaSourceAcquisitionAdapter,
    _build_endpoint,
)
from whale.ingest.usecases.dtos.acquisition_execution_options import (
    AcquisitionExecutionOptions,
)
from whale.ingest.usecases.dtos.acquisition_item_data import AcquisitionItemData
from whale.ingest.usecases.dtos.source_acquisition_request import SourceAcquisitionRequest
from whale.ingest.usecases.dtos.source_connection_data import SourceConnectionData


def _mk_conn(**params: object) -> SourceConnectionData:
    return SourceConnectionData(
        host=str(params.get("host", "")),
        port=int(params.get("port", 0)),
        ied_name=str(params.get("ied_name", "IED_01")),
        ld_name=str(params.get("ld_name", "LD_01")),
        namespace_uri=str(params.get("namespace_uri", "")),
    )


def _mk_request(*, items=None, conn=None):
    return SourceAcquisitionRequest(
        request_id="request-1",
        task_id=1,
        execution=AcquisitionExecutionOptions(
            protocol="opcua",
            transport="tcp",
            acquisition_mode="ONCE",
            interval_ms=1000,
            max_iteration=1,
            request_timeout_ms=500,
            freshness_timeout_ms=30000,
            alive_timeout_ms=60000,
        ),
        connections=[conn or _mk_conn()],
        items=items or [],
    )


# -- endpoint ----------------------------------------------------------------

def test_resolve_endpoint_from_request_protocol_transport() -> None:
    conn = _mk_conn(host="192.168.1.1", port=4840)
    req = _mk_request(conn=conn)
    assert _build_endpoint(req.execution, conn) == "opcua.tcp://192.168.1.1:4840"


def test_resolve_endpoint_empty_when_no_info() -> None:
    req = _mk_request(conn=_mk_conn(host="", port=0))
    assert _build_endpoint(req.execution, req.connections[0]) == ""


# -- node IDs ----------------------------------------------------------------

def test_node_id_from_locator() -> None:
    conn = _mk_conn(namespace_uri="urn:windfarm:2wtg")
    item = AcquisitionItemData(key="TotW", profile_item_id=1, relative_path="WTG_001/MMXU1.TotW.mag.f")
    assert OpcUaSourceAcquisitionAdapter._resolve_node_ids(conn, [item]) == [
        "nsu=urn:windfarm:2wtg;s=WTG_001/MMXU1.TotW.mag.f"
    ]


def test_node_id_without_namespace_uri() -> None:
    item = AcquisitionItemData(key="Spd", profile_item_id=2, relative_path="MMXU1.Spd.mag.f")
    assert OpcUaSourceAcquisitionAdapter._resolve_node_ids(_mk_conn(), [item]) == ["s=MMXU1.Spd.mag.f"]


def test_node_id_locator_already_qualified() -> None:
    conn = _mk_conn(namespace_uri="urn:windfarm:2wtg")
    item = AcquisitionItemData(key="TotW", profile_item_id=1, relative_path="nsu=urn:other;s=Custom.Val")
    assert OpcUaSourceAcquisitionAdapter._resolve_node_ids(conn, [item]) == ["nsu=urn:other;s=Custom.Val"]
