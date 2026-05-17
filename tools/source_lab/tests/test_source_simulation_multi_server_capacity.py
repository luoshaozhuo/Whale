"""Pytest entrypoint for source_lab capacity scanner.

This test is a thin wrapper over tools.source_lab.access and keeps scanner
logic outside pytest.

Notes:
- SOURCE_SIM_PROFILE_SCHEDULER_MODE is ignored by capacity scanner behavior.
- For capacity scans, OPC UA default backend recommendation is open62541.
"""

from __future__ import annotations

import pytest

from tools.source_lab.access import print_capacity_report
from tools.source_lab.access.config import from_env_for_simulator
from tools.source_lab.access.capacity import scan_source_capacity
from tools.source_lab.access.providers.simulator import SimulatorSourceProvider


@pytest.mark.load
def test_source_simulation_multi_server_capacity() -> None:
    config = from_env_for_simulator()
    provider = SimulatorSourceProvider.from_env()

    result = scan_source_capacity(config, provider=provider)
    print_capacity_report(result)

    assert result.levels
    assert result.has_accepted_level
