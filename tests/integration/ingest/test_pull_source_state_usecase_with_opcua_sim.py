"""Integration tests for ingest use cases with the OPC UA simulator and file store."""

from __future__ import annotations

import asyncio
import csv
import socket
import time
from contextlib import closing
from pathlib import Path
from threading import Event

import pytest

from tools.opcua_sim.models import OpcUaServerConfig
from tools.opcua_sim.server_runtime import OpcUaServerRuntime
from whale.ingest.adapters.source.opcua_source_acquisition_adapter import (
    OpcUaSourceAcquisitionAdapter,
)
from whale.ingest.adapters.source.static_source_acquisition_port_registry import (
    StaticSourceAcquisitionPortRegistry,
)
from whale.ingest.adapters.state.file_source_state_cache import (
    FileSourceStateCache,
)
from whale.ingest.usecases.dtos.acquisition_item_data import AcquisitionItemData
from whale.ingest.usecases.dtos.acquisition_status import AcquisitionStatus
from whale.ingest.usecases.dtos.source_acquisition_definition import (
    SourceAcquisitionDefinition,
)
from whale.ingest.usecases.dtos.source_acquisition_request import (
    SourceAcquisitionRequest,
)
from whale.ingest.usecases.dtos.source_connection_data import SourceConnectionData
from whale.ingest.usecases.dtos.source_runtime_config_data import (
    SourceRuntimeConfigData,
)
from whale.ingest.usecases.pull_source_state_usecase import (
    PullSourceStateUseCase,
)
from whale.ingest.usecases.subscribe_source_state_usecase import (
    SubscribeSourceStateUseCase,
)

TEST_DURATION_SECONDS = 10.0
TEST_INTERVAL_SECONDS = 0.1
TEST_INTERVAL_MS = int(TEST_INTERVAL_SECONDS * 1000)
MODEL_ID = "goldwind_gw121_opcua"
VARIABLE_KEYS = ("TotW", "Spd", "WS")
TEST_OUTPUT_DIR = Path("tests/tmp/ingest")


class StaticSourceAcquisitionDefinitionPort:
    """Return one prebuilt acquisition definition for the configured runtime config."""

    def __init__(self, definition: SourceAcquisitionDefinition) -> None:
        """Store the static definition returned by the fake port."""
        self._definition = definition

    def get_config(
        self,
        runtime_config: SourceRuntimeConfigData,
    ) -> SourceAcquisitionDefinition:
        """Return acquisition config for the matching runtime config."""
        del runtime_config
        return self._definition


class PollingSubscriptionSourceAcquisitionAdapter(OpcUaSourceAcquisitionAdapter):
    """Drive subscription tests through repeated live reads against the simulator."""

    async def subscribe(
        self,
        request: object,
    ) -> None:
        """Continuously read from the source and forward the results as subscription updates."""
        from whale.ingest.usecases.dtos.source_subscription_request import (
            SourceSubscriptionRequest,
        )

        if not isinstance(request, SourceSubscriptionRequest):
            raise TypeError(f"Expected SourceSubscriptionRequest, got {type(request).__name__}")
        if request.stop_requested is None:
            raise ValueError("Subscription request must provide a stop callback.")
        if request.state_received is None:
            raise ValueError("Subscription request must provide a state callback.")

        sleep_seconds = self._resolve_publishing_interval_ms(request.connection) / 1000.0

        while not request.stop_requested():
            states = await self.read(
                SourceAcquisitionRequest(
                    source_id=request.source_id,
                    connection=request.connection,
                    items=list(request.items),
                )
            )
            if states:
                await request.state_received(states)
            await asyncio.sleep(sleep_seconds)


def _get_free_port() -> int:
    """Return one currently available local TCP port."""
    with closing(socket.socket(socket.AF_INET, socket.SOCK_STREAM)) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _build_runtime_config(
    *,
    acquisition_mode: str,
    interval_ms: int,
) -> SourceRuntimeConfigData:
    """Build one runtime config snapshot for the integration scenario."""
    return SourceRuntimeConfigData(
        runtime_config_id=101,
        source_id="WTG_01",
        protocol="opcua",
        acquisition_mode=acquisition_mode,
        interval_ms=interval_ms,
        enabled=True,
    )


def _build_definition(endpoint: str) -> SourceAcquisitionDefinition:
    """Build one concrete acquisition definition for the OPC UA simulator."""
    return SourceAcquisitionDefinition(
        model_id=MODEL_ID,
        connection=SourceConnectionData(
            endpoint=endpoint,
            params={
                "security_policy": "None",
                "security_mode": "None",
                "namespace_uri": "urn:windfarm:2wtg",
                "publishing_interval_ms": TEST_INTERVAL_MS,
            },
        ),
        items=[
            AcquisitionItemData(
                key=variable_key,
                locator=f"s=WTG_01.{variable_key}",
                display_name=variable_key,
            )
            for variable_key in VARIABLE_KEYS
        ],
    )


def _build_pull_use_case(
    definition: SourceAcquisitionDefinition,
    state_cache_port: FileSourceStateCache,
) -> PullSourceStateUseCase:
    """Build the pull use case with the real OPC UA adapter and file store."""
    return PullSourceStateUseCase(
        acquisition_definition_port=StaticSourceAcquisitionDefinitionPort(definition),
        acquisition_port_registry=StaticSourceAcquisitionPortRegistry(
            {"opcua": OpcUaSourceAcquisitionAdapter()}
        ),
        state_cache_port=state_cache_port,
    )


def _build_subscribe_use_case(
    definition: SourceAcquisitionDefinition,
    state_cache_port: FileSourceStateCache,
) -> SubscribeSourceStateUseCase:
    """Build the subscribe use case with the real OPC UA adapter and file store."""
    return SubscribeSourceStateUseCase(
        acquisition_definition_port=StaticSourceAcquisitionDefinitionPort(definition),
        acquisition_port_registry=StaticSourceAcquisitionPortRegistry(
            {"opcua": PollingSubscriptionSourceAcquisitionAdapter()}
        ),
        state_cache_port=state_cache_port,
    )


def _build_file_store(output_path: Path) -> FileSourceStateCache:
    """Build the file-backed store and clear the current test output file."""
    TEST_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    if output_path.exists():
        output_path.unlink()
    return FileSourceStateCache(TEST_OUTPUT_DIR)


def _read_rows(output_path: Path) -> list[dict[str, str]]:
    """Read all captured rows from one CSV output file."""
    if not output_path.exists():
        return []
    with output_path.open("r", encoding="utf-8", newline="") as input_file:
        return list(csv.DictReader(input_file))


def _read_snapshot(output_path: Path) -> tuple[float, float, float] | None:
    """Read one numeric snapshot from the latest CSV rows for every test variable."""
    rows = _read_rows(output_path)
    if len(rows) < len(VARIABLE_KEYS):
        return None

    latest_rows_by_key: dict[str, dict[str, str]] = {}
    for row in rows:
        latest_rows_by_key[row["variable_key"]] = row
    if len(latest_rows_by_key) != len(VARIABLE_KEYS):
        return None

    values_by_key = {key: float(row["value"]) for key, row in latest_rows_by_key.items()}
    return (
        values_by_key["TotW"],
        values_by_key["Spd"],
        values_by_key["WS"],
    )


def _assert_rows_written(output_path: Path) -> None:
    """Assert that one CSV output file contains captured rows for every test variable."""
    rows = _read_rows(output_path)
    latest_rows_by_key: dict[str, dict[str, str]] = {}
    for row in rows:
        latest_rows_by_key[row["variable_key"]] = row

    assert sorted(latest_rows_by_key) == ["Spd", "TotW", "WS"]
    assert all(row["device_code"] == "WTG_01" for row in latest_rows_by_key.values())
    assert all(row["model_id"] == MODEL_ID for row in latest_rows_by_key.values())
    assert all(float(row["value"]) > 0 for row in latest_rows_by_key.values())
    assert all(row["source_observed_at"] for row in latest_rows_by_key.values())
    assert all(row["received_at"] for row in latest_rows_by_key.values())
    assert all(row["updated_at"] for row in latest_rows_by_key.values())


def _assert_series_changed(
    snapshots: list[tuple[float, tuple[float, float, float]]],
) -> None:
    """Assert that every variable changed multiple times during the test window."""
    assert len(snapshots) >= 40

    rounded_series = list(zip(*[[round(value, 4) for value in values] for _, values in snapshots]))
    assert all(len(set(series)) >= 10 for series in rounded_series)


async def _run_polling_for_duration(
    use_case: PullSourceStateUseCase,
    runtime_config: SourceRuntimeConfigData,
    output_path: Path,
) -> list[tuple[float, tuple[float, float, float]]]:
    """Execute repeated pull acquisition for the configured duration."""
    snapshots: list[tuple[float, tuple[float, float, float]]] = []
    started_at = time.monotonic()

    while True:
        elapsed = time.monotonic() - started_at
        if elapsed >= TEST_DURATION_SECONDS:
            return snapshots

        result = (await use_case.execute([runtime_config]))[0]
        assert result.status is AcquisitionStatus.SUCCEEDED

        snapshot = _read_snapshot(output_path)
        if snapshot is not None:
            snapshots.append((elapsed, snapshot))

        await asyncio.sleep(TEST_INTERVAL_SECONDS)


async def _run_subscription_for_duration(
    use_case: SubscribeSourceStateUseCase,
    runtime_config: SourceRuntimeConfigData,
    output_path: Path,
) -> list[tuple[float, tuple[float, float, float]]]:
    """Run subscription acquisition for the configured duration and sample CSV output."""
    stop_event = Event()
    snapshots: list[tuple[float, tuple[float, float, float]]] = []
    started_at = time.monotonic()
    subscription_task = asyncio.create_task(use_case.execute((runtime_config,), stop_event))

    try:
        while True:
            await asyncio.sleep(TEST_INTERVAL_SECONDS)
            elapsed = time.monotonic() - started_at
            if elapsed >= TEST_DURATION_SECONDS:
                break

            snapshot = _read_snapshot(output_path)
            if snapshot is not None:
                snapshots.append((elapsed, snapshot))
    finally:
        stop_event.set()
        await subscription_task

    return snapshots


@pytest.mark.integration
def test_pull_source_state_once_writes_rows_to_sqlite() -> None:
    """Write one latest-state snapshot into the file store for one ONCE acquisition."""
    output_path = TEST_OUTPUT_DIR / "read-results.csv"
    store_port = _build_file_store(output_path)
    endpoint = f"opc.tcp://127.0.0.1:{_get_free_port()}"
    definition = _build_definition(endpoint)
    runtime_config = _build_runtime_config(acquisition_mode="ONCE", interval_ms=0)
    use_case = _build_pull_use_case(definition, store_port)

    with OpcUaServerRuntime(
        nodeset_path=Path("tools/opcua_sim/templates/OPCUANodeSet.xml"),
        config=OpcUaServerConfig(
            name="WTG_01",
            endpoint=endpoint,
            security_policy="None",
            security_mode="None",
            update_interval_seconds=TEST_INTERVAL_SECONDS,
        ),
    ):
        result = asyncio.run(use_case.execute([runtime_config]))[0]

    assert result.runtime_config_id == 101
    assert result.status is AcquisitionStatus.SUCCEEDED
    assert result.error_message is None
    _assert_rows_written(output_path)


@pytest.mark.integration
def test_pull_source_state_polling_writes_changing_rows_to_sqlite_for_ten_seconds() -> None:
    """Continuously poll for 10 seconds and persist changing simulator values into CSV."""
    output_path = TEST_OUTPUT_DIR / "polling-results.csv"
    store_port = _build_file_store(output_path)
    endpoint = f"opc.tcp://127.0.0.1:{_get_free_port()}"
    definition = _build_definition(endpoint)
    runtime_config = _build_runtime_config(
        acquisition_mode="POLLING",
        interval_ms=TEST_INTERVAL_MS,
    )
    use_case = _build_pull_use_case(definition, store_port)

    with OpcUaServerRuntime(
        nodeset_path=Path("tools/opcua_sim/templates/OPCUANodeSet.xml"),
        config=OpcUaServerConfig(
            name="WTG_01",
            endpoint=endpoint,
            security_policy="None",
            security_mode="None",
            update_interval_seconds=TEST_INTERVAL_SECONDS,
        ),
    ):
        snapshots = asyncio.run(_run_polling_for_duration(use_case, runtime_config, output_path))

    _assert_rows_written(output_path)
    _assert_series_changed(snapshots)


@pytest.mark.integration
def test_subscribe_source_state_writes_changing_rows_to_sqlite_for_ten_seconds() -> None:
    """Continuously subscribe for 10 seconds and persist changing simulator values into CSV."""
    output_path = TEST_OUTPUT_DIR / "subscription-results.csv"
    store_port = _build_file_store(output_path)
    endpoint = f"opc.tcp://127.0.0.1:{_get_free_port()}"
    definition = _build_definition(endpoint)
    runtime_config = _build_runtime_config(
        acquisition_mode="SUBSCRIPTION",
        interval_ms=TEST_INTERVAL_MS,
    )
    use_case = _build_subscribe_use_case(definition, store_port)

    with OpcUaServerRuntime(
        nodeset_path=Path("tools/opcua_sim/templates/OPCUANodeSet.xml"),
        config=OpcUaServerConfig(
            name="WTG_01",
            endpoint=endpoint,
            security_policy="None",
            security_mode="None",
            update_interval_seconds=TEST_INTERVAL_SECONDS,
        ),
    ):
        snapshots = asyncio.run(
            _run_subscription_for_duration(use_case, runtime_config, output_path)
        )

    _assert_rows_written(output_path)
    _assert_series_changed(snapshots)
