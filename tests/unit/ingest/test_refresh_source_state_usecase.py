"""Unit tests for the refresh-source-state use case."""

from __future__ import annotations

from datetime import UTC, datetime

from whale.ingest.usecases.dtos.acquired_node_state import AcquiredNodeState
from whale.ingest.usecases.dtos.acquisition_item_data import AcquisitionItemData
from whale.ingest.usecases.dtos.acquisition_status import AcquisitionStatus
from whale.ingest.usecases.dtos.refresh_source_state_command import (
    RefreshSourceStateCommand,
)
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
from whale.ingest.usecases.refresh_source_state_usecase import (
    RefreshSourceStateUseCase,
)


class FakeRuntimeConfigPort:
    """Fake runtime-config port for use-case tests."""

    def __init__(self, config: SourceRuntimeConfigData | None) -> None:
        """Store the config returned by `get_by_id`."""
        self._config = config

    def list_enabled(self) -> list[SourceRuntimeConfigData]:
        """Return the enabled config if present and enabled."""
        if self._config is None or not self._config.enabled:
            return []
        return [self._config]

    def get_by_id(self, runtime_config_id: int) -> SourceRuntimeConfigData:
        """Return the configured runtime row or raise when it is missing."""
        if self._config is None or self._config.runtime_config_id != runtime_config_id:
            raise LookupError(f"Runtime config `{runtime_config_id}` was not found.")
        return self._config


class FakeAcquisitionDefinitionPort:
    """Fake acquisition-definition port for use-case tests."""

    def __init__(self, definition: SourceAcquisitionDefinition | None) -> None:
        """Store the definition returned to the role."""
        self._definition = definition

    def get_read_once_definition(
        self,
        runtime_config_id: int,
    ) -> SourceAcquisitionDefinition:
        """Return the configured definition or raise when it is missing."""
        if self._definition is None or self._definition.runtime_config_id != runtime_config_id:
            raise LookupError(f"Definition for `{runtime_config_id}` was not found.")
        return self._definition


class FakeSourceAcquisitionPort:
    """Fake source-acquisition port for use-case tests."""

    def __init__(self, states: list[AcquiredNodeState], error: Exception | None = None) -> None:
        """Store the configured acquisition behavior."""
        self._states = list(states)
        self._error = error
        self.requests: list[SourceAcquisitionRequest] = []

    def read_once(self, request: SourceAcquisitionRequest) -> list[AcquiredNodeState]:
        """Capture the request and return the configured states."""
        self.requests.append(request)
        if self._error is not None:
            raise self._error
        return list(self._states)

    def subscribe(self, request: object) -> None:
        """Unused subscription hook required by the port contract."""
        del request
        raise NotImplementedError


class FakeNodeStateStorePort:
    """Fake source-state repository for use-case tests."""

    def __init__(self, updated_count: int = 0) -> None:
        """Store the count returned from `upsert_many`."""
        self._updated_count = updated_count
        self.calls: list[tuple[str, list[AcquiredNodeState]]] = []

    def upsert_many(
        self,
        source_id: str,
        acquired_states: list[AcquiredNodeState],
    ) -> int:
        """Capture the call and return the configured update count."""
        self.calls.append((source_id, list(acquired_states)))
        return self._updated_count


def _build_runtime_config(enabled: bool = True) -> SourceRuntimeConfigData:
    """Build one runtime config for use-case tests."""
    return SourceRuntimeConfigData(
        runtime_config_id=101,
        source_id="WTG_01",
        protocol="opcua",
        acquisition_mode="ONCE",
        interval_ms=0,
        enabled=enabled,
    )


def _build_definition() -> SourceAcquisitionDefinition:
    """Build one acquisition definition for use-case tests."""
    return SourceAcquisitionDefinition(
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
                address="nsu=urn:windfarm:2wtg;s=WTG_01.TotW",
                namespace_uri="urn:windfarm:2wtg",
                display_name="TotW",
            )
        ],
    )


def _build_states() -> list[AcquiredNodeState]:
    """Build one acquired-state list for use-case tests."""
    return [
        AcquiredNodeState(
            source_id="WTG_01",
            node_key="TotW",
            node_id="nsu=urn:windfarm:2wtg;s=WTG_01.TotW",
            value="1200.0",
            quality=None,
            observed_at=datetime.now(tz=UTC),
        )
    ]


def test_execute_returns_failed_when_runtime_config_is_missing() -> None:
    """Return FAILED instead of raising for a missing runtime config."""
    store_port = FakeNodeStateStorePort(updated_count=1)
    use_case = RefreshSourceStateUseCase(
        runtime_config_port=FakeRuntimeConfigPort(None),
        acquisition_definition_port=FakeAcquisitionDefinitionPort(_build_definition()),
        acquisition_port=FakeSourceAcquisitionPort(_build_states()),
        store_port=store_port,
    )

    result = use_case.execute(RefreshSourceStateCommand(runtime_config_id=101))

    assert result.status == "FAILED"
    assert "Runtime config `101` was not found." == result.error_message
    assert result.source_id == ""
    assert result.updated_count == 0
    assert store_port.calls == []
    assert result.status is AcquisitionStatus.FAILED


def test_execute_returns_disabled_without_querying_repository() -> None:
    """Return DISABLED when the runtime config is disabled."""
    store_port = FakeNodeStateStorePort(updated_count=1)
    use_case = RefreshSourceStateUseCase(
        runtime_config_port=FakeRuntimeConfigPort(_build_runtime_config(enabled=False)),
        acquisition_definition_port=FakeAcquisitionDefinitionPort(_build_definition()),
        acquisition_port=FakeSourceAcquisitionPort(_build_states()),
        store_port=store_port,
    )

    result = use_case.execute(RefreshSourceStateCommand(runtime_config_id=101))

    assert result.status == "DISABLED"
    assert result.source_id == "WTG_01"
    assert result.updated_count == 0
    assert store_port.calls == []
    assert result.status is AcquisitionStatus.DISABLED


def test_execute_returns_failed_when_definition_is_missing() -> None:
    """Return FAILED when the acquisition definition cannot be built."""
    store_port = FakeNodeStateStorePort(updated_count=1)
    use_case = RefreshSourceStateUseCase(
        runtime_config_port=FakeRuntimeConfigPort(_build_runtime_config()),
        acquisition_definition_port=FakeAcquisitionDefinitionPort(None),
        acquisition_port=FakeSourceAcquisitionPort(_build_states()),
        store_port=store_port,
    )

    result = use_case.execute(RefreshSourceStateCommand(runtime_config_id=101))

    assert result.status == "FAILED"
    assert "Definition for `101` was not found." == result.error_message
    assert result.source_id == "WTG_01"
    assert store_port.calls == []
    assert result.status is AcquisitionStatus.FAILED


def test_execute_returns_succeeded_and_persists_states() -> None:
    """Persist acquired states and expose execution counts."""
    states = _build_states()
    acquisition_port = FakeSourceAcquisitionPort(states)
    store_port = FakeNodeStateStorePort(updated_count=1)
    use_case = RefreshSourceStateUseCase(
        runtime_config_port=FakeRuntimeConfigPort(_build_runtime_config()),
        acquisition_definition_port=FakeAcquisitionDefinitionPort(_build_definition()),
        acquisition_port=acquisition_port,
        store_port=store_port,
    )

    result = use_case.execute(RefreshSourceStateCommand(runtime_config_id=101))

    assert result.status == "SUCCEEDED"
    assert result.received_count == 1
    assert result.updated_count == 1
    assert result.error_message is None
    assert len(acquisition_port.requests) == 1
    assert store_port.calls == [("WTG_01", states)]
    assert result.status is AcquisitionStatus.SUCCEEDED


def test_execute_returns_empty_when_acquisition_has_no_results() -> None:
    """Return EMPTY without persisting any state rows."""
    store_port = FakeNodeStateStorePort(updated_count=99)
    use_case = RefreshSourceStateUseCase(
        runtime_config_port=FakeRuntimeConfigPort(_build_runtime_config()),
        acquisition_definition_port=FakeAcquisitionDefinitionPort(_build_definition()),
        acquisition_port=FakeSourceAcquisitionPort([]),
        store_port=store_port,
    )

    result = use_case.execute(RefreshSourceStateCommand(runtime_config_id=101))

    assert result.status == "EMPTY"
    assert result.received_count == 0
    assert result.updated_count == 0
    assert store_port.calls == []
    assert result.status is AcquisitionStatus.EMPTY


def test_execute_returns_failed_when_acquisition_raises() -> None:
    """Return FAILED instead of bubbling one acquisition exception."""
    store_port = FakeNodeStateStorePort(updated_count=1)
    use_case = RefreshSourceStateUseCase(
        runtime_config_port=FakeRuntimeConfigPort(_build_runtime_config()),
        acquisition_definition_port=FakeAcquisitionDefinitionPort(_build_definition()),
        acquisition_port=FakeSourceAcquisitionPort([], error=ConnectionError("boom")),
        store_port=store_port,
    )

    result = use_case.execute(RefreshSourceStateCommand(runtime_config_id=101))

    assert result.status == "FAILED"
    assert result.error_message == "boom"
    assert result.updated_count == 0
    assert store_port.calls == []
    assert result.status is AcquisitionStatus.FAILED
