"""Integration tests for simulator-fleet assembly from repository data."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
import math
import time
from typing import Any, Protocol

import pytest
from asyncua import ua  # type: ignore[import-untyped]
from asyncua.sync import Client  # type: ignore[import-untyped]

from whale.ingest.adapters.config.source_runtime_config_repository import (
    SourceRuntimeConfigRepository,
)
from tools.source_simulation.domain import (
    SimulatedPoint,
    SimulatedSource,
    SourceConnection,
    UpdateConfig,
)
from tools.source_simulation.fleet import SourceSimulatorFleet

RUN_DURATION_SECONDS = 10.0
UPDATE_INTERVAL_SECONDS = 0.5
SAMPLE_INTERVAL_SECONDS = 0.1
INTERVAL_TOLERANCE_SECONDS = 0.2


@dataclass(frozen=True)
class OpcUaReadPoint:
    node_id: str
    value: Any
    source_timestamp: datetime | None
    server_timestamp: datetime | None


class SimulationClient(Protocol):
    def __enter__(self) -> "SimulationClient": ...
    def __exit__(self, exc_type: object, exc: object, tb: object) -> None: ...
    def readable_server(self, *, namespace_uri: str) -> bool: ...
    def variable_count(
        self,
        *,
        source_name: str,
        expected_points: tuple[SimulatedPoint, ...],
        namespace_uri: str,
    ) -> int: ...
    def build_sample_node_ids(
        self,
        *,
        source_name: str,
        sample_points: tuple[SimulatedPoint, ...],
        namespace_uri: str,
    ) -> list[str]: ...
    def collect_samples(
        self,
        *,
        node_ids: list[str],
        duration_seconds: float,
        poll_interval_seconds: float = SAMPLE_INTERVAL_SECONDS,
    ) -> list[list[OpcUaReadPoint]]: ...


class OpcUaSimulationClient:
    def __init__(self, endpoint: str) -> None:
        self._endpoint = endpoint
        self._client: Client | None = None
        self._namespace_index_by_uri: dict[str, int] = {}

    def __enter__(self) -> "OpcUaSimulationClient":
        client = Client(self._endpoint)
        client.connect()
        self._client = client
        return self

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        if self._client is not None:
            self._client.disconnect()
            self._client = None

    def readable_server(self, *, namespace_uri: str) -> bool:
        windfarm = self._objects_node().get_child(f"{self._namespace_index(namespace_uri)}:WindFarm")
        return len(windfarm.get_children()) == 1

    def variable_count(
        self,
        *,
        source_name: str,
        expected_points: tuple[SimulatedPoint, ...],
        namespace_uri: str,
    ) -> int:
        turbine = self._node(f"ns={self._namespace_index(namespace_uri)};s={source_name}")
        _ = expected_points
        return len(turbine.get_children())

    def build_sample_node_ids(
        self,
        *,
        source_name: str,
        sample_points: tuple[SimulatedPoint, ...],
        namespace_uri: str,
    ) -> list[str]:
        namespace_index = self._namespace_index(namespace_uri)
        return [
            f"ns={namespace_index};s={source_name}.{point.key}"
            for point in sample_points
        ]

    def collect_samples(
        self,
        *,
        node_ids: list[str],
        duration_seconds: float,
        poll_interval_seconds: float = SAMPLE_INTERVAL_SECONDS,
    ) -> list[list[OpcUaReadPoint]]:
        deadline = time.monotonic() + duration_seconds
        nodes = [self._node(node_id) for node_id in node_ids]
        samples: list[list[OpcUaReadPoint]] = []

        while time.monotonic() < deadline:
            data_values = self._client_or_raise().read_attributes(nodes, attr=ua.AttributeIds.Value)
            samples.append(
                [
                    OpcUaReadPoint(
                        node_id=node_id,
                        value=data_value.Value.Value,
                        source_timestamp=getattr(data_value, "SourceTimestamp", None),
                        server_timestamp=getattr(data_value, "ServerTimestamp", None),
                    )
                    for node_id, data_value in zip(node_ids, data_values, strict=True)
                ]
            )
            time.sleep(poll_interval_seconds)

        return samples

    def _client_or_raise(self) -> Client:
        if self._client is None:
            raise RuntimeError("Simulation client must be connected before reading")
        return self._client

    def _objects_node(self) -> object:
        return self._client_or_raise().nodes.objects

    def _node(self, node_id: str) -> object:
        return self._client_or_raise().get_node(node_id)

    def _namespace_index(self, namespace_uri: str) -> int:
        if namespace_uri not in self._namespace_index_by_uri:
            self._namespace_index_by_uri[namespace_uri] = self._client_or_raise().get_namespace_index(
                namespace_uri
            )
        return self._namespace_index_by_uri[namespace_uri]

def _simulation_client_factory(*, protocol: str, endpoint: str) -> SimulationClient:
    normalized_protocol = protocol.strip().lower().replace("_", "").replace("-", "")
    if normalized_protocol == "opcua":
        return OpcUaSimulationClient(endpoint)
    raise NotImplementedError(f"No simulation client registered for protocol `{protocol}`")


def _mean_interval(timestamps: list[datetime]) -> float:
    intervals = [
        (current - previous).total_seconds()
        for previous, current in zip(timestamps, timestamps[1:], strict=False)
    ]
    return sum(intervals) / len(intervals)


def _changed_source_timestamps(
    samples: list[list[OpcUaReadPoint]],
    *,
    point_index: int,
) -> list[datetime]:
    timestamps: list[datetime] = []
    previous_point = samples[0][point_index]
    for batch in samples[1:]:
        current_point = batch[point_index]
        if (
            current_point.value != previous_point.value
            and current_point.source_timestamp is not None
            and current_point.source_timestamp != previous_point.source_timestamp
        ):
            timestamps.append(current_point.source_timestamp)
        previous_point = current_point
    return timestamps


def _distinct_values(
    samples: list[list[OpcUaReadPoint]],
    *,
    point_index: int,
) -> set[Any]:
    return {batch[point_index].value for batch in samples}


@pytest.mark.integration
def test_simulator_fleet_can_be_assembled_from_repository_data() -> None:
    """Assemble one simulator fleet for every server-group combination."""
    runtime_repo = SourceRuntimeConfigRepository()
    server_rows = runtime_repo.list_servers(
        group_by=("signal_profile_id", "application_protocol"),
        first_group_only=False,
    )
    assert server_rows, "Expected at least one simulator server row from repository"

    grouped_server_rows: dict[tuple[int, str], list] = defaultdict(list)
    for row in server_rows:
        grouped_server_rows[(row.signal_profile_id, row.application_protocol)].append(row)

    assert grouped_server_rows, "Expected at least one grouped server combination"

    for (selected_profile_id, application_protocol), current_group_rows in grouped_server_rows.items():
        point_rows = runtime_repo.list_profile_items(selected_profile_id)
        assert point_rows, f"Expected profile items for signal_profile_id={selected_profile_id}"

        unique_shared_paths: set[str] = set()
        profile_points: list[SimulatedPoint] = []
        for row in point_rows:
            point = SimulatedPoint(
                ln_name=row.ln_name,
                do_name=row.do_name,
                unit=row.unit.strip() if row.unit is not None else None,
                data_type=row.data_type,
            )
            profile_points.append(point)
            unique_shared_paths.add(point.key)

        points = tuple(profile_points)
        assert points, f"Expected at least one shared point for profile {selected_profile_id}"

        sources = [
            SimulatedSource(
                connection=SourceConnection(
                    name=(row.asset_code or row.ld_name or row.ied_name or f"source_{row.endpoint_id}").strip(),
                    ied_name=row.ied_name.strip(),
                    ld_name=row.ld_name.strip(),
                    host=row.host,
                    port=int(row.port),
                    transport=row.transport,
                    protocol=row.application_protocol,
                    params={"namespace_uri": (row.namespace_uri or "").strip()},
                ),
                points=points,
            )
            for row in current_group_rows
        ]
        assert sources, f"Expected at least one source for group {(selected_profile_id, application_protocol)}"

        fleet = SourceSimulatorFleet.create(
            sources=sources,
            update_config=UpdateConfig(interval_seconds=UPDATE_INTERVAL_SECONDS, update_count=2),
        )

        first_source = sources[0]
        namespace_uri = str(first_source.connection.params.get("namespace_uri") or "").strip()
        assert namespace_uri, "Expected namespace_uri for OPC UA simulator source"
        sample_points = points[: min(3, len(points))]
        assert sample_points, f"Expected sample points to validate for profile {selected_profile_id}"

        with fleet:
            readable_server_count = 0
            for source in sources:
                endpoint = f"opc.tcp://{source.connection.host}:{source.connection.port}"
                with _simulation_client_factory(
                    protocol=source.connection.protocol,
                    endpoint=endpoint,
                ) as simulation_client:
                    if simulation_client.readable_server(namespace_uri=namespace_uri):
                        readable_server_count += 1

            assert readable_server_count == len(current_group_rows), (
                f"Expected readable simulator count {len(current_group_rows)} "
                f"for group {(selected_profile_id, application_protocol)}, "
                f"got {readable_server_count}"
            )

            endpoint = f"opc.tcp://{first_source.connection.host}:{first_source.connection.port}"
            with _simulation_client_factory(
                protocol=first_source.connection.protocol,
                endpoint=endpoint,
            ) as simulation_client:
                assert simulation_client.variable_count(
                    source_name=first_source.connection.name,
                    expected_points=points,
                    namespace_uri=namespace_uri,
                ) == len(unique_shared_paths), (
                    f"Expected variable count {len(unique_shared_paths)} "
                    f"for group {(selected_profile_id, application_protocol)}"
                )

                sample_node_ids = simulation_client.build_sample_node_ids(
                    source_name=first_source.connection.name,
                    sample_points=sample_points,
                    namespace_uri=namespace_uri,
                )
                samples = simulation_client.collect_samples(
                    node_ids=sample_node_ids,
                    duration_seconds=RUN_DURATION_SECONDS,
                )
                assert samples, "Expected at least one sampled batch"

                initial_reads = samples[0]
                for point, read_point in zip(sample_points, initial_reads, strict=True):
                    value = read_point.value
                    if point.data_type.strip().upper() == "BOOLEAN":
                        assert isinstance(value, bool)
                    else:
                        assert isinstance(value, (int, float, str))

                change_timestamps = _changed_source_timestamps(samples, point_index=0)
                assert len(change_timestamps) >= 20, (
                    f"Expected stable updates for at least {RUN_DURATION_SECONDS:.0f}s "
                    f"for group {(selected_profile_id, application_protocol)}, "
                    f"got {len(change_timestamps)} changes"
                )
                mean_interval = _mean_interval(change_timestamps)
                assert math.isclose(
                    mean_interval,
                    UPDATE_INTERVAL_SECONDS,
                    abs_tol=INTERVAL_TOLERANCE_SECONDS,
                ), (
                    f"Expected mean update interval near {UPDATE_INTERVAL_SECONDS}s "
                    f"for group {(selected_profile_id, application_protocol)}, "
                    f"got {mean_interval:.3f}s"
                )

                for index, point in enumerate(sample_points):
                    distinct_values = _distinct_values(samples, point_index=index)
                    assert len(distinct_values) >= 3, (
                        f"Expected point {point.key} to change randomly over "
                        f"{RUN_DURATION_SECONDS:.0f}s for group "
                        f"{(selected_profile_id, application_protocol)}, "
                        f"got only {len(distinct_values)} distinct values"
                    )

            assert len(fleet.simulators) == len(current_group_rows)
            assert len(fleet._shared_points) == len(unique_shared_paths)
