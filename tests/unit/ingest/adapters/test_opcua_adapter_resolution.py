"""Unit tests for OpcUaSourceAcquisitionAdapter endpoint / node ID resolution."""

from __future__ import annotations

from whale.ingest.adapters.source.opcua_source_acquisition_adapter import (
    OpcUaSourceAcquisitionAdapter,
)
from whale.ingest.usecases.dtos.acquisition_item_data import AcquisitionItemData
from whale.ingest.usecases.dtos.source_acquisition_request import SourceAcquisitionRequest
from whale.ingest.usecases.dtos.source_connection_data import SourceConnectionData


def _mk_conn(**params: object) -> SourceConnectionData:
    return SourceConnectionData(params={k: v for k, v in params.items()})


def _mk_request(*, items=None, conn=None, resolved_endpoint=None, resolved_node_ids=None):
    return SourceAcquisitionRequest(
        source_id="test",
        connection=conn or SourceConnectionData(),
        items=items or [],
        resolved_endpoint=resolved_endpoint,
        resolved_node_ids=resolved_node_ids,
    )


# -- endpoint ----------------------------------------------------------------

def test_resolve_endpoint_uses_resolved_endpoint() -> None:
    req = _mk_request(resolved_endpoint="opc.tcp://10.0.0.1:4840")
    assert OpcUaSourceAcquisitionAdapter._resolve_endpoint(req) == "opc.tcp://10.0.0.1:4840"


def test_resolve_endpoint_from_connection_endpoint() -> None:
    conn = SourceConnectionData(endpoint="opc.tcp://192.168.1.1:4840")
    req = _mk_request(conn=conn)
    assert OpcUaSourceAcquisitionAdapter._resolve_endpoint(req) == "opc.tcp://192.168.1.1:4840"


def test_resolve_endpoint_empty_when_no_info() -> None:
    assert OpcUaSourceAcquisitionAdapter._resolve_endpoint(_mk_request()) == ""


def test_resolve_endpoint_precedence() -> None:
    conn = SourceConnectionData(endpoint="opc.tcp://1.2.3.4:9999")
    req = _mk_request(conn=conn, resolved_endpoint="opc.tcp://explicit:4840")
    assert OpcUaSourceAcquisitionAdapter._resolve_endpoint(req) == "opc.tcp://explicit:4840"


# -- node IDs ----------------------------------------------------------------

def test_resolve_node_ids_shortcut() -> None:
    req = _mk_request(resolved_node_ids=["nsu=urn:x;s=A.B"])
    assert OpcUaSourceAcquisitionAdapter._resolve_node_ids(req) == ["nsu=urn:x;s=A.B"]


def test_node_id_from_locator() -> None:
    conn = SourceConnectionData(params={"namespace_uri": "urn:windfarm:2wtg"})
    item = AcquisitionItemData(key="TotW", locator="WTG_001/MMXU1.TotW.mag.f")
    req = _mk_request(conn=conn, items=[item])
    assert OpcUaSourceAcquisitionAdapter._resolve_node_ids(req) == [
        "nsu=urn:windfarm:2wtg;s=WTG_001/MMXU1.TotW.mag.f"
    ]


def test_node_id_without_namespace_uri() -> None:
    item = AcquisitionItemData(key="Spd", locator="MMXU1.Spd.mag.f")
    req = _mk_request(items=[item])
    assert OpcUaSourceAcquisitionAdapter._resolve_node_ids(req) == ["s=MMXU1.Spd.mag.f"]


def test_node_id_locator_already_qualified() -> None:
    conn = SourceConnectionData(params={"namespace_uri": "urn:windfarm:2wtg"})
    item = AcquisitionItemData(key="TotW", locator="nsu=urn:other;s=Custom.Val")
    req = _mk_request(conn=conn, items=[item])
    assert OpcUaSourceAcquisitionAdapter._resolve_node_ids(req) == ["nsu=urn:other;s=Custom.Val"]
