"""Integration tests for simulator-fleet assembly from repository data."""

from __future__ import annotations

import asyncio
from collections import defaultdict
from datetime import datetime
import math
import time
from typing import Any

import pytest

from whale.ingest.adapters.config.source_runtime_config_repository import (
    SourceRuntimeConfigRepository,
)
from tools.source_simulation.adapters.registry import build_source_reader
from tools.source_simulation.domain import (
    SimulatedPoint,
    SimulatedSource,
    SourceNodeInfo,
    SourceReadPoint,
    SourceConnection,
    UpdateConfig,
)
from tools.source_simulation.fleet import SourceSimulatorFleet

RUN_DURATION_SECONDS = 10.0
UPDATE_INTERVAL_SECONDS = 0.5
SAMPLE_INTERVAL_SECONDS = 0.1
INTERVAL_TOLERANCE_SECONDS = 0.2


async def _list_nodes(source: SimulatedSource) -> tuple[SourceNodeInfo, ...]:
    async with build_source_reader(source.connection) as reader:
        return await reader.list_nodes()


async def _read_points(
    source: SimulatedSource,
    *,
    node_paths: list[str],
) -> tuple[SourceReadPoint, ...]:
    async with build_source_reader(source.connection) as reader:
        return await reader.read(node_paths, fast_mode=False)


async def _collect_samples(
    source: SimulatedSource,
    *,
    node_paths: list[str],
    duration_seconds: float,
    poll_interval_seconds: float = SAMPLE_INTERVAL_SECONDS,
) -> list[tuple[SourceReadPoint, ...]]:
    deadline = time.monotonic() + duration_seconds
    samples: list[tuple[SourceReadPoint, ...]] = []

    async with build_source_reader(source.connection) as reader:
        while time.monotonic() < deadline:
            samples.append(await reader.read(node_paths, fast_mode=False))
            await asyncio.sleep(poll_interval_seconds)

    return samples


def _changed_source_timestamps(
    samples: list[tuple[SourceReadPoint, ...]],
    *,
    point_index: int,
) -> list[datetime]:
    timestamps: list[datetime] = []
    previous_point = samples[0][point_index]
    for batch in samples[1:]:
        current_point = batch[point_index]
        if (
            current_point.source_timestamp is not None
            and current_point.source_timestamp != previous_point.source_timestamp
        ):
            timestamps.append(current_point.source_timestamp)
        previous_point = current_point
    return timestamps


def _mean_interval(timestamps: list[datetime]) -> float:
    intervals = [
        (current - previous).total_seconds()
        for previous, current in zip(timestamps, timestamps[1:], strict=False)
    ]
    return sum(intervals) / len(intervals)


def _distinct_values(
    samples: list[tuple[SourceReadPoint, ...]],
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

    for (
        selected_profile_id,
        application_protocol,
    ), current_group_rows in grouped_server_rows.items():
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
                    name=(
                        row.asset_code or row.ld_name or row.ied_name or f"source_{row.endpoint_id}"
                    ).strip(),
                    ied_name=row.ied_name.strip(),
                    ld_name=row.ld_name.strip(),
                    host=row.host,
                    port=int(row.port),
                    transport=row.transport,
                    protocol=row.application_protocol,
                    namespace_uri=row.namespace_uri.strip(),
                ),
                points=points,
            )
            for row in current_group_rows
        ]
        assert (
            sources
        ), f"Expected at least one source for group {(selected_profile_id, application_protocol)}"

        fleet = SourceSimulatorFleet.create(
            sources=sources,
            update_config=UpdateConfig(interval_seconds=UPDATE_INTERVAL_SECONDS, update_count=2),
        )

        first_source = sources[0]
        namespace_uri = str(first_source.connection.namespace_uri or "").strip()
        assert namespace_uri, "Expected namespace_uri for OPC UA simulator source"
        sample_points = points[: min(3, len(points))]
        assert (
            sample_points
        ), f"Expected sample points to validate for profile {selected_profile_id}"

        with fleet:
            readable_server_count = 0
            for source in sources:
                nodes = asyncio.run(_list_nodes(source))
                if nodes:
                    readable_server_count += 1

            assert readable_server_count == len(current_group_rows), (
                f"Expected readable simulator count {len(current_group_rows)} "
                f"for group {(selected_profile_id, application_protocol)}, "
                f"got {readable_server_count}"
            )

            node_infos = asyncio.run(_list_nodes(first_source))
            assert len(node_infos) == len(unique_shared_paths), (
                f"Expected variable count {len(unique_shared_paths)} "
                f"for group {(selected_profile_id, application_protocol)}"
            )

            node_path_by_key = {
                f"{node_info.ln_name}.{node_info.do_name}": node_info.node_path
                for node_info in node_infos
            }
            sample_node_paths = [node_path_by_key[point.key] for point in sample_points]
            initial_reads = asyncio.run(
                _read_points(
                    first_source,
                    node_paths=sample_node_paths,
                )
            )
            for point, read_point in zip(sample_points, initial_reads, strict=True):
                value = read_point.value
                if point.data_type.strip().upper() == "BOOLEAN":
                    assert isinstance(value, bool)
                else:
                    assert isinstance(value, (int, float, str))

            updated_points = list(points[:2])
            assert updated_points, "Expected at least one fleet update point"
            observed_point = next(
                (point for point in updated_points if point.data_type != "BOOLEAN"),
                updated_points[0],
            )
            observed_node_path = node_path_by_key[observed_point.key]

            samples = asyncio.run(
                _collect_samples(
                    first_source,
                    node_paths=[observed_node_path],
                    duration_seconds=RUN_DURATION_SECONDS,
                )
            )
            assert samples, "Expected sampled batches for update-period validation"

            distinct_values = _distinct_values(samples, point_index=0)
            assert len(distinct_values) >= 2, (
                f"Expected observed point {observed_point.key} to change over time "
                f"for group {(selected_profile_id, application_protocol)}, "
                f"got only {len(distinct_values)} distinct value(s)"
            )

            change_timestamps = _changed_source_timestamps(samples, point_index=0)
            assert len(change_timestamps) >= 10, (
                f"Expected stable source-timestamp updates for group "
                f"{(selected_profile_id, application_protocol)}, "
                f"got only {len(change_timestamps)} timestamp changes"
            )

            mean_interval = _mean_interval(change_timestamps)
            assert math.isclose(
                mean_interval,
                UPDATE_INTERVAL_SECONDS,
                abs_tol=INTERVAL_TOLERANCE_SECONDS,
            ), (
                f"Expected mean source-timestamp interval near {UPDATE_INTERVAL_SECONDS}s "
                f"for group {(selected_profile_id, application_protocol)}, "
                f"got {mean_interval:.3f}s"
            )
