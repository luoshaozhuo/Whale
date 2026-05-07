"""Unit tests for the source-acquisition-definition DTO."""

from __future__ import annotations

from whale.ingest.usecases.dtos.acquisition_item_data import AcquisitionItemData
from whale.ingest.usecases.dtos.source_acquisition_definition import (
    SourceAcquisitionDefinition,
)
from whale.ingest.usecases.dtos.source_connection_data import SourceConnectionData


def test_definition_preserves_config_fields() -> None:
    """Expose acquisition config fields without mutating their content."""
    definition = SourceAcquisitionDefinition(
        ld_id="goldwind_gw121_opcua",
        connection=SourceConnectionData(
            endpoint="opc.tcp://127.0.0.1:4840",
            params={
                "security_policy": "None",
                "security_mode": "None",
                "namespace_uri": "urn:windfarm:2wtg",
            },
        ),
        items=[
            AcquisitionItemData(
                key="TotW",
                locator="s=WTG_01.TotW",
            )
        ],
    )

    assert definition.ld_id == "goldwind_gw121_opcua"
    assert definition.connection.endpoint == "opc.tcp://127.0.0.1:4840"
    assert definition.items[0].key == "TotW"
