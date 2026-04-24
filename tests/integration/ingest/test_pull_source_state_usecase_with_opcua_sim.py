"""Integration test for pull-source-state use case with OPC UA simulator."""

from __future__ import annotations

import asyncio
import socket
from contextlib import closing, redirect_stdout
from io import StringIO
from pathlib import Path

import pytest

from tools.opcua_sim.models import OpcUaServerConfig
from tools.opcua_sim.server_runtime import OpcUaServerRuntime
from whale.ingest.adapters.source.opcua_source_acquisition_adapter import (
    OpcUaSourceAcquisitionAdapter,
)
from whale.ingest.adapters.source.static_source_acquisition_port_registry import (
    StaticSourceAcquisitionPortRegistry,
)
from whale.ingest.ports.store.source_state_store_port import SourceStateStorePort
from whale.ingest.usecases.dtos.acquired_node_state import AcquiredNodeState
from whale.ingest.usecases.dtos.acquisition_item_data import AcquisitionItemData
from whale.ingest.usecases.dtos.acquisition_status import AcquisitionStatus
from whale.ingest.usecases.dtos.source_acquisition_definition import (
    SourceAcquisitionDefinition,
)
from whale.ingest.usecases.dtos.source_connection_data import SourceConnectionData
from whale.ingest.usecases.dtos.source_runtime_config_data import (
    SourceRuntimeConfigData,
)
from whale.ingest.usecases.pull_source_state_usecase import (
    PullSourceStateUseCase,
)


class StaticSourceAcquisitionDefinitionPort:
    """Return one prebuilt acquisition definition for the test runtime config."""

    def __init__(self, definition: SourceAcquisitionDefinition) -> None:
        """Store the definition returned by the fake port."""
        self._definition = definition

    def resolve_definition(
        self,
        runtime_config: SourceRuntimeConfigData,
    ) -> SourceAcquisitionDefinition:
        """Return the configured definition for the matching runtime config."""
        del runtime_config
        return self._definition

    def get_config(
        self,
        runtime_config: SourceRuntimeConfigData,
    ) -> SourceAcquisitionDefinition:
        """Return acquisition config for the matching runtime config."""
        return self.resolve_definition(runtime_config)


class TerminalSourceStateStore(SourceStateStorePort):
    """Write acquired source states to terminal output for integration testing."""

    def __init__(self) -> None:
        """Initialize captured state rows."""
        self.rows: list[AcquiredNodeState] = []

    def store_many(
        self,
        model_id: str,
        acquired_states: list[AcquiredNodeState],
    ) -> int:
        """Print acquired states and return the accepted row count."""
        self.rows.extend(acquired_states)
        for state in acquired_states:
            print(
                "[terminal-state] "
                f"model_id={model_id} "
                f"source_id={state.source_id} "
                f"node_key={state.node_key} "
                f"node_id={state.node_id} "
                f"value={state.value}"
            )
        return len(acquired_states)


def _get_free_port() -> int:
    """Return one currently available local TCP port."""
    with closing(socket.socket(socket.AF_INET, socket.SOCK_STREAM)) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _build_runtime_config() -> SourceRuntimeConfigData:
    """Build the runtime config snapshot used by the integration test."""
    return SourceRuntimeConfigData(
        runtime_config_id=101,
        source_id="WTG_01",
        protocol="opcua",
        acquisition_mode="ONCE",
        interval_ms=0,
        enabled=True,
    )


def _build_definition(endpoint: str) -> SourceAcquisitionDefinition:
    """Build a concrete acquisition definition for the OPC UA simulator."""
    return SourceAcquisitionDefinition(
        model_id="goldwind_gw121_opcua",
        connection=SourceConnectionData(
            endpoint=endpoint,
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
                display_name="TotW",
            ),
            AcquisitionItemData(
                key="Spd",
                locator="s=WTG_01.Spd",
                display_name="Spd",
            ),
        ],
    )


@pytest.mark.integration
def test_pull_source_state_reads_opcua_sim_and_writes_terminal_store() -> None:
    """Read from a live OPC UA simulator and write acquired states to terminal."""
    endpoint = f"opc.tcp://127.0.0.1:{_get_free_port()}"
    definition = _build_definition(endpoint)
    runtime_config = _build_runtime_config()
    terminal_store = TerminalSourceStateStore()
    use_case = PullSourceStateUseCase(
        acquisition_definition_port=StaticSourceAcquisitionDefinitionPort(definition),
        acquisition_port_registry=StaticSourceAcquisitionPortRegistry(
            {"opcua": OpcUaSourceAcquisitionAdapter()}
        ),
        store_port=terminal_store,
    )
    terminal_output = StringIO()

    with (
        OpcUaServerRuntime(
            nodeset_path=Path("tools/opcua_sim/templates/OPCUANodeSet.xml"),
            config=OpcUaServerConfig(
                name="WTG_01",
                endpoint=endpoint,
                security_policy="None",
                security_mode="None",
                update_interval_seconds=0,
            ),
        ),
        redirect_stdout(terminal_output),
    ):
        result = asyncio.run(use_case.execute([runtime_config]))[0]

    output = terminal_output.getvalue()

    assert result.runtime_config_id == 101
    assert result.status is AcquisitionStatus.SUCCEEDED
    assert result.error_message is None
    assert result.started_at <= result.ended_at
    assert [state.node_key for state in terminal_store.rows] == ["TotW", "Spd"]
    assert all(float(state.value) > 0 for state in terminal_store.rows)
    assert "[terminal-state] model_id=goldwind_gw121_opcua source_id=WTG_01 node_key=TotW" in output
    assert "[terminal-state] model_id=goldwind_gw121_opcua source_id=WTG_01 node_key=Spd" in output
