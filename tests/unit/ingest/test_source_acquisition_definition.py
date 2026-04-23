"""Unit tests for the source-acquisition-definition DTO."""

from __future__ import annotations

from whale.ingest.usecases.dtos.acquisition_item_data import AcquisitionItemData
from whale.ingest.usecases.dtos.source_acquisition_definition import (
    SourceAcquisitionDefinition,
)
from whale.ingest.usecases.dtos.source_connection_data import SourceConnectionData


def test_to_request_preserves_definition_fields() -> None:
    """Convert a definition into a request without dropping fields."""
    definition = SourceAcquisitionDefinition(
        runtime_config_id=101,
        source_id="WTG_01",
        source_name="WTG_01",
        protocol="opcua",
        connection=SourceConnectionData(
            endpoint="opc.tcp://127.0.0.1:4840",
            security_policy="None",
            security_mode="None",
            update_interval_ms=100,
        ),
        items=[
            AcquisitionItemData(
                key="TotW",
                address="s=WTG_01.TotW",
                namespace_uri="urn:windfarm:2wtg",
                display_name="TotW",
            )
        ],
    )

    request = definition.to_request()

    assert request.runtime_config_id == definition.runtime_config_id
    assert request.source_id == definition.source_id
    assert request.source_name == definition.source_name
    assert request.protocol == definition.protocol
    assert request.connection == definition.connection
    assert request.items == definition.items
    assert request.items is not definition.items
