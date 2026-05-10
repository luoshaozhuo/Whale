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
            host="127.0.0.1",
            port=4840,
            ied_name="IED_WTG_01",
            ld_name="WTG_01",
            namespace_uri="urn:windfarm:2wtg",
            security_policy="None",
            security_mode="None",
        ),
        items=[
            AcquisitionItemData(
                key="TotW",
                profile_item_id=1,
                relative_path="MMXU1.TotW.mag.f",
            )
        ],
    )

    assert definition.ld_id == "goldwind_gw121_opcua"
    assert definition.connection.ied_name == "IED_WTG_01"
    assert definition.connection.ld_name == "WTG_01"
    assert definition.connection.namespace_uri == "urn:windfarm:2wtg"
    assert definition.items[0].key == "TotW"
    assert definition.items[0].profile_item_id == 1
    assert definition.items[0].relative_path == "MMXU1.TotW.mag.f"
