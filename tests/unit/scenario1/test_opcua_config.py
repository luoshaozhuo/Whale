"""Unit tests for OPC UA config import parsing."""

from __future__ import annotations

import pytest

from whale.ingest.application.services.opcua_config_import_service import (
    OpcUaConfigImportError,
    build_connection_rows,
    load_connection_rows_from_yaml,
    load_nodeset_records,
)


@pytest.mark.unit
def test_load_connection_configs_from_yaml_matches_template(
    sample_opcua_connections_path: str,
) -> None:
    """Parse all simulator connection rows from the YAML template."""
    connections = load_connection_rows_from_yaml(sample_opcua_connections_path)

    assert [item.name for item in connections] == ["WTG_01", "WTG_02"]
    assert connections[0].endpoint.startswith("opc.tcp://127.0.0.1:")
    assert connections[0].update_interval_ms == 100


@pytest.mark.unit
def test_load_node_templates_from_nodeset_matches_template(
    sample_nodeset_path: str,
) -> None:
    """Parse pollable wind turbine variables from the NodeSet template."""
    nodeset = load_nodeset_records(sample_nodeset_path)

    assert [item.browse_name for item in nodeset.variables] == ["1:TotW", "1:Spd", "1:WS"]
    assert all(item.parent_node_id == "ns=1;s=WindTurbineType" for item in nodeset.variables)
    assert len(nodeset.namespace_uris) == 2
    assert len(nodeset.aliases) > 0
    assert len(nodeset.object_types) == 1
    assert len(nodeset.objects) == 3
    assert len(nodeset.references) > 0


@pytest.mark.unit
def test_build_connection_rows_requires_name() -> None:
    """Raise when a connection row misses a required field."""
    with pytest.raises(OpcUaConfigImportError, match="name"):
        build_connection_rows(
            [
                {
                    "endpoint": "opc.tcp://127.0.0.1:4840",
                    "security_policy": "None",
                    "security_mode": "None",
                    "update_interval_ms": 100,
                }
            ]
        )


@pytest.mark.unit
def test_load_nodeset_records_parses_object_type_and_variable_value(
    sample_nodeset_path: str,
) -> None:
    """Parse object types and variable initial values from the NodeSet."""
    nodeset = load_nodeset_records(sample_nodeset_path)

    assert nodeset.object_types[0].node_id == "ns=1;s=WindTurbineType"
    assert nodeset.variables[0].initial_value_text == "0.0"
