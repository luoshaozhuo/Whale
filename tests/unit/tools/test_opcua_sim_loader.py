"""Unit tests for OPC UA simulator bootstrap helpers."""

from __future__ import annotations

from xml.etree import ElementTree

import pytest

from tools.opcua_sim.server_runtime import (
    DEFAULT_VARIABLE_VALUES,
    build_simulated_variable_value,
    load_server_config,
)

NODESET_NAMESPACE = "http://opcfoundation.org/UA/2011/03/UANodeSet.xsd"


@pytest.mark.unit
def test_load_server_config_reads_named_connection(
    sample_opcua_connections_path: str,
) -> None:
    """Load the configured endpoint for one named simulator connection."""
    config = load_server_config(sample_opcua_connections_path, "WTG_02")

    assert config.name == "WTG_02"
    assert config.endpoint == "opc.tcp://127.0.0.1:4841"
    assert config.update_interval_seconds == 0.2


@pytest.mark.unit
def test_load_server_config_rejects_missing_connection(
    sample_opcua_connections_path: str,
) -> None:
    """Raise a clear error when the requested connection name is missing."""
    with pytest.raises(ValueError, match="missing"):
        load_server_config(sample_opcua_connections_path, "missing")


@pytest.mark.unit
def test_sample_nodeset_declares_object_type_as_subtype(
    sample_nodeset_path: str,
) -> None:
    """Declare the custom object type with a subtype reference for asyncua import."""
    root = ElementTree.parse(sample_nodeset_path).getroot()
    namespace = {"ua": NODESET_NAMESPACE}
    reference = root.find(
        ".//ua:UAObjectType[@NodeId='ns=1;s=WindTurbineType']/ua:References/"
        "ua:Reference[@ReferenceType='HasSubtype']",
        namespace,
    )

    assert reference is not None
    assert reference.get("IsForward") == "false"
    assert (reference.text or "").strip() == "BaseObjectType"


@pytest.mark.unit
def test_build_simulated_variable_value_offsets_variable_peaks_by_phase() -> None:
    """Offset simulator peaks by 90 degrees across consecutive variables."""
    sample_times = [index * 0.05 for index in range(100)]
    peak_times = {}

    for variable_name, mean in DEFAULT_VARIABLE_VALUES.items():
        series = [
            build_simulated_variable_value(variable_name, mean, elapsed, 0.0)
            for elapsed in sample_times
        ]
        peak_times[variable_name] = sample_times[max(range(len(series)), key=series.__getitem__)]

    assert peak_times["Spd"] < peak_times["TotW"] < peak_times["WS"]
