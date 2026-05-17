"""Preflight checks for capacity scanner."""

from __future__ import annotations

import asyncio
import socket

from whale.shared.source.access import build_source_access_adapter
from tools.source_lab.access.model import (
    CapacityScanConfig,
    CapacityStatus,
    PreflightResult,
    ServerPreflightResult,
)
from tools.source_lab.access.providers.base import SourceRuntimeSpec


def _tcp_reachable(host: str, port: int, timeout_s: float) -> bool:
    """Check whether one TCP endpoint is reachable."""

    try:
        with socket.create_connection((host, port), timeout=timeout_s):
            return True
    except OSError:
        return False


def _preflight_concurrency(config: CapacityScanConfig) -> int:
    """Resolve bounded preflight concurrency for one run."""

    return max(1, min(config.max_concurrent_reads, 16))


async def _run_one_preflight(
    config: CapacityScanConfig,
    source: SourceRuntimeSpec,
    semaphore: asyncio.Semaphore,
) -> ServerPreflightResult:
    async with semaphore:
        tcp_ok = _tcp_reachable(
            source.endpoint.host,
            source.endpoint.port,
            timeout_s=config.preflight_tcp_timeout_s,
        )
        endpoint_label = f"{source.endpoint.host}:{source.endpoint.port}"
        if not tcp_ok:
            return ServerPreflightResult(
                server_name=source.endpoint.name,
                endpoint=endpoint_label,
                tcp_reachable=False,
                protocol_connect_ok=False,
                readable_point_count=0,
                expected_point_count=len(source.points),
                missing_response_timestamp=False,
                status=CapacityStatus.FAIL,
                failure_reason="tcp_unreachable",
            )

        try:
            adapter = build_source_access_adapter(
                config.protocol,
                source.endpoint,
                source.points,
                read_timeout_s=config.read_timeout_s,
                opcua_client_backend=config.opcua_client_backend,
            )
        except ValueError as exc:
            return ServerPreflightResult(
                server_name=source.endpoint.name,
                endpoint=endpoint_label,
                tcp_reachable=True,
                protocol_connect_ok=False,
                readable_point_count=0,
                expected_point_count=len(source.points),
                missing_response_timestamp=False,
                status=CapacityStatus.FAIL,
                failure_reason=str(exc),
            )

        try:
            await adapter.connect()
            await adapter.prepare_read()
            tick = await adapter.read_tick(expected_value_count=len(source.points))
        except Exception as exc:
            return ServerPreflightResult(
                server_name=source.endpoint.name,
                endpoint=endpoint_label,
                tcp_reachable=True,
                protocol_connect_ok=False,
                readable_point_count=0,
                expected_point_count=len(source.points),
                missing_response_timestamp=False,
                status=CapacityStatus.FAIL,
                failure_reason=f"preflight_exception:{type(exc).__name__}",
            )
        finally:
            await adapter.close()

        return ServerPreflightResult(
            server_name=source.endpoint.name,
            endpoint=endpoint_label,
            tcp_reachable=True,
            protocol_connect_ok=tick.error is None,
            readable_point_count=tick.value_count,
            expected_point_count=len(source.points),
            missing_response_timestamp=tick.response_timestamp_s is None,
            status=CapacityStatus.PASS if tick.error is None else CapacityStatus.FAIL,
            failure_reason=tick.error or "",
        )


def run_preflight(
    config: CapacityScanConfig,
    sources: tuple[SourceRuntimeSpec, ...],
) -> PreflightResult:
    """Run preflight checks for all sources in one server_count group."""

    async def _run_all() -> tuple[ServerPreflightResult, ...]:
        max_concurrent = _preflight_concurrency(config)
        semaphore = asyncio.Semaphore(max_concurrent)

        tasks = [
            _run_one_preflight(config, source, semaphore)
            for source in sources
        ]
        results = await asyncio.gather(*tasks)
        return tuple(results)

    return PreflightResult(by_server=asyncio.run(_run_all()))
