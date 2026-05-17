"""Tests for field-mode source provider."""

from __future__ import annotations

import pytest

from whale.shared.source.access.model import SourceEndpointSpec, SourcePointSpec
from tools.source_lab.access.model import (
    CapacityMode,
    CapacityScanConfig,
)
from tools.source_lab.access.providers.field import FieldSourceProvider


def _config(
    endpoints: tuple[SourceEndpointSpec, ...],
    points: tuple[SourcePointSpec, ...],
) -> CapacityScanConfig:
    return CapacityScanConfig(
        mode=CapacityMode.FIELD,
        protocol="opcua",
        endpoints=endpoints,
        points=points,
        server_count_start=1,
        server_count_step=1,
        server_count_max=1,
        hz_start=10.0,
        hz_step=10.0,
        hz_max=10.0,
        process_count=1,
        coroutines_per_process=0,
    )


def test_field_provider_build_and_started() -> None:
    provider = FieldSourceProvider()
    endpoints = (
        SourceEndpointSpec(
            name="field-1",
            host="127.0.0.1",
            port=4840,
            protocol="opcua",
        ),
    )
    points = (SourcePointSpec(address="IED.LD.LN.DO"),)
    config = _config(endpoints, points)

    sources = provider.build_sources(config, server_count=1)

    assert len(sources) == 1
    with provider.started(sources):
        pass


def test_field_provider_requires_endpoints() -> None:
    provider = FieldSourceProvider()
    config = _config((), (SourcePointSpec(address="IED.LD.LN.DO"),))

    with pytest.raises(ValueError, match="field mode requires endpoints"):
        provider.build_sources(config, server_count=1)


def test_field_provider_requires_points() -> None:
    provider = FieldSourceProvider()
    endpoints = (
        SourceEndpointSpec(
            name="field-1",
            host="127.0.0.1",
            port=4840,
            protocol="opcua",
        ),
    )
    config = _config(endpoints, ())

    with pytest.raises(ValueError, match="field mode requires points"):
        provider.build_sources(config, server_count=1)


def test_field_provider_server_count_exceeds_endpoints() -> None:
    provider = FieldSourceProvider()
    endpoints = (
        SourceEndpointSpec(
            name="field-1",
            host="127.0.0.1",
            port=4840,
            protocol="opcua",
        ),
    )
    points = (SourcePointSpec(address="IED.LD.LN.DO"),)
    config = _config(endpoints, points)

    with pytest.raises(ValueError, match="server_count exceeds available endpoints"):
        provider.build_sources(config, server_count=2)
