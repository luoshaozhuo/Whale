"""Lightweight tests for OPC UA capacity adapter helpers."""

from __future__ import annotations

from whale.shared.source.access.opcua import normalize_opcua_node_id


def test_normalize_node_id_adds_s_prefix() -> None:
    assert normalize_opcua_node_id("IED.LD.LN.DO") == "s=IED.LD.LN.DO"


def test_normalize_node_id_keeps_existing_s_prefix() -> None:
    assert normalize_opcua_node_id("s=IED.LD.LN.DO") == "s=IED.LD.LN.DO"
