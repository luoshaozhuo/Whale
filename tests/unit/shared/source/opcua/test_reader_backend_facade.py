"""Unit tests for OpcUaSourceReader facade delegation and backend guard rails."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime

import pytest

from whale.shared.source.models import Batch, SourceConnectionProfile
from whale.shared.source.opcua.backends.asyncua_backend import AsyncuaOpcUaClientBackend
from whale.shared.source.opcua.backends.base import (
    AsyncuaPreparedReadPlan,
    PreparedReadPlan,
    RawOpcUaReadResult,
)
from whale.shared.source.opcua.reader import OpcUaSourceReader


@dataclass(frozen=True, slots=True)
class _FakePlan:
    """Minimal prepared-read plan for facade unit tests."""

    node_paths: tuple[str, ...]


class _FakeBackend:
    """Small backend spy used to validate facade delegation."""

    def __init__(self) -> None:
        self.connected = False
        self.prepared_addresses: tuple[str, ...] | None = None
        self.raw_plan: PreparedReadPlan | None = None
        self.plan = _FakePlan(node_paths=("ns=2;s=IED001.LD0.WPPD1.TotW",))
        self.raw_result = RawOpcUaReadResult(
            ok=True,
            data_values=(),
            response_timestamp=datetime(2026, 5, 15, tzinfo=UTC),
        )

    async def connect(self) -> None:
        self.connected = True

    async def disconnect(self) -> None:
        self.connected = False

    @property
    def namespace_index(self) -> int | None:
        return 2

    def prepare_read(self, addresses: tuple[str, ...] | list[str]) -> PreparedReadPlan:
        self.prepared_addresses = tuple(addresses)
        return self.plan

    async def read_prepared_raw(self, plan: PreparedReadPlan) -> RawOpcUaReadResult:
        self.raw_plan = plan
        return self.raw_result


def _connection() -> SourceConnectionProfile:
    """Build one minimal connection profile."""

    return SourceConnectionProfile(
        endpoint="opc.tcp://127.0.0.1:4840",
        namespace_uri="urn:test:reader",
    )


@pytest.mark.unit
def test_reader_initialization_builds_backend(monkeypatch: pytest.MonkeyPatch) -> None:
    """Reader should build exactly one backend through the shared factory."""

    fake_backend = _FakeBackend()
    observed_connection: SourceConnectionProfile | None = None

    def _fake_build_backend(connection: SourceConnectionProfile) -> _FakeBackend:
        nonlocal observed_connection
        observed_connection = connection
        return fake_backend

    monkeypatch.setattr(
        "whale.shared.source.opcua.reader.build_opcua_client_backend",
        _fake_build_backend,
    )

    reader = OpcUaSourceReader(_connection())

    assert observed_connection == _connection()
    assert reader._backend is fake_backend  # noqa: SLF001


@pytest.mark.unit
def test_prepare_read_delegates_to_backend(monkeypatch: pytest.MonkeyPatch) -> None:
    """prepare_read should delegate address preparation to the configured backend."""

    fake_backend = _FakeBackend()
    monkeypatch.setattr(
        "whale.shared.source.opcua.reader.build_opcua_client_backend",
        lambda connection: fake_backend,
    )
    reader = OpcUaSourceReader(_connection())

    plan = reader.prepare_read(["s=IED001.LD0.WPPD1.TotW"])

    assert plan is fake_backend.plan
    assert fake_backend.prepared_addresses == ("s=IED001.LD0.WPPD1.TotW",)


@pytest.mark.unit
def test_read_accepts_mode_keyword_without_include_metadata(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Public reader API should use mode=... instead of include_metadata."""

    fake_backend = _FakeBackend()
    monkeypatch.setattr(
        "whale.shared.source.opcua.reader.build_opcua_client_backend",
        lambda connection: fake_backend,
    )
    reader = OpcUaSourceReader(_connection())

    observed: dict[str, object] = {}

    async def _fake_read_prepared(plan: PreparedReadPlan, *, mode: str) -> Batch:
        observed["plan"] = plan
        observed["mode"] = mode
        return Batch(
            changes=(),
            batch_observed_at=datetime(2026, 5, 15, tzinfo=UTC),
            client_received_at=datetime(2026, 5, 15, tzinfo=UTC),
            availability_status="VALID",
        )

    reader.read_prepared = _fake_read_prepared  # type: ignore[method-assign]

    batch = asyncio.run(reader.read(["s=IED001.LD0.WPPD1.TotW"], mode="full"))

    assert isinstance(batch, Batch)
    assert fake_backend.prepared_addresses == ("s=IED001.LD0.WPPD1.TotW",)
    assert observed["plan"] is fake_backend.plan
    assert observed["mode"] == "full"


@pytest.mark.unit
def test_read_prepared_raw_delegates_to_backend(monkeypatch: pytest.MonkeyPatch) -> None:
    """read_prepared_raw should delegate directly to the backend raw polling API."""

    fake_backend = _FakeBackend()
    monkeypatch.setattr(
        "whale.shared.source.opcua.reader.build_opcua_client_backend",
        lambda connection: fake_backend,
    )
    reader = OpcUaSourceReader(_connection())

    result = asyncio.run(reader.read_prepared_raw(fake_backend.plan))

    assert result is fake_backend.raw_result
    assert fake_backend.raw_plan is fake_backend.plan


@pytest.mark.unit
def test_reader_no_longer_exposes_diagnostic_raw_read_api() -> None:
    """The facade should no longer expose the diagnostic-only raw-read API."""

    reader = OpcUaSourceReader(_connection())

    assert not hasattr(reader, "read_prepared_raw_diagnostic")


@pytest.mark.unit
def test_open62541_backend_full_batch_read_raises_clear_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Full batch reads should explain why open62541 is not supported yet."""

    monkeypatch.setenv("SOURCE_SIM_OPCUA_CLIENT_BACKEND", "open62541")
    monkeypatch.delenv("WHALE_OPCUA_CLIENT_BACKEND", raising=False)
    reader = OpcUaSourceReader(_connection())

    with pytest.raises(NotImplementedError, match="full Batch read requires asyncua backend"):
        asyncio.run(
            reader.read_prepared(
                _FakePlan(node_paths=("ns=2;s=IED001.LD0.WPPD1.TotW",)),
                mode="full",
            )
        )


@pytest.mark.unit
def test_open62541_backend_value_only_read_raises_clear_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Value-only batch reads should explain why open62541 is not supported yet."""

    monkeypatch.setenv("SOURCE_SIM_OPCUA_CLIENT_BACKEND", "open62541")
    monkeypatch.delenv("WHALE_OPCUA_CLIENT_BACKEND", raising=False)
    reader = OpcUaSourceReader(_connection())

    with pytest.raises(
        NotImplementedError,
        match="value_only Batch read requires backend values; open62541 runner currently returns count-only raw results",
    ):
        asyncio.run(
            reader.read_prepared(
                _FakePlan(node_paths=("ns=2;s=IED001.LD0.WPPD1.TotW",)),
                mode="value_only",
            )
        )


@pytest.mark.unit
def test_open62541_backend_subscription_raises_clear_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Subscriptions should stay asyncua-only with one clear explanation."""

    monkeypatch.setenv("SOURCE_SIM_OPCUA_CLIENT_BACKEND", "open62541")
    monkeypatch.delenv("WHALE_OPCUA_CLIENT_BACKEND", raising=False)
    reader = OpcUaSourceReader(_connection())

    async def _on_data_change(batch: Batch) -> None:
        return None

    with pytest.raises(NotImplementedError, match="subscription currently requires asyncua client subscription API"):
        asyncio.run(
            reader.start_subscription(
                ["s=IED001.LD0.WPPD1.TotW"],
                interval_ms=250,
                on_data_change=_on_data_change,
            )
        )


@pytest.mark.unit
def test_open62541_backend_list_nodes_raises_clear_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Browsing should stay asyncua-only with one clear explanation."""

    monkeypatch.setenv("SOURCE_SIM_OPCUA_CLIENT_BACKEND", "open62541")
    monkeypatch.delenv("WHALE_OPCUA_CLIENT_BACKEND", raising=False)
    reader = OpcUaSourceReader(_connection())

    with pytest.raises(NotImplementedError, match="browse currently requires asyncua node browsing API"):
        asyncio.run(reader.list_nodes())


@pytest.mark.unit
def test_asyncua_full_read_uses_full_batch_builder(monkeypatch: pytest.MonkeyPatch) -> None:
    """Asyncua backend should continue into the full Batch conversion path."""

    backend = AsyncuaOpcUaClientBackend(_connection())
    plan = AsyncuaPreparedReadPlan(
        node_paths=("ns=2;s=IED001.LD0.WPPD1.TotW",),
        nodes=(),
        read_params=object(),  # type: ignore[arg-type]
    )
    raw_result = RawOpcUaReadResult(
        ok=True,
        data_values=(),
        response_timestamp=datetime(2026, 5, 15, tzinfo=UTC),
    )

    monkeypatch.setattr(
        "whale.shared.source.opcua.reader.build_opcua_client_backend",
        lambda connection: backend,
    )
    reader = OpcUaSourceReader(_connection())
    monkeypatch.setattr(backend, "prepare_read", lambda addresses: plan)
    monkeypatch.setattr(backend, "read_prepared_raw", lambda prepared_plan: asyncio.sleep(0, result=raw_result))

    observed: dict[str, object] = {}

    def _fake_build_full_batch(
        prepared_plan: PreparedReadPlan,
        data_values: object,
        *,
        response_timestamp: datetime | None,
    ) -> Batch:
        observed["plan"] = prepared_plan
        observed["data_values"] = data_values
        observed["response_timestamp"] = response_timestamp
        return Batch(
            changes=(),
            batch_observed_at=datetime(2026, 5, 15, tzinfo=UTC),
            client_received_at=datetime(2026, 5, 15, tzinfo=UTC),
            availability_status="VALID",
        )

    reader._build_full_batch = _fake_build_full_batch  # type: ignore[method-assign]  # noqa: SLF001

    batch = asyncio.run(reader.read(["s=IED001.LD0.WPPD1.TotW"], mode="full"))

    assert isinstance(batch, Batch)
    assert observed["plan"] is plan
    assert observed["data_values"] == ()
    assert observed["response_timestamp"] == raw_result.response_timestamp


@pytest.mark.unit
def test_asyncua_value_only_read_uses_value_only_path(monkeypatch: pytest.MonkeyPatch) -> None:
    """Asyncua backend should continue into the value-only read path."""

    backend = AsyncuaOpcUaClientBackend(_connection())
    plan = AsyncuaPreparedReadPlan(
        node_paths=("ns=2;s=IED001.LD0.WPPD1.TotW",),
        nodes=(),
        read_params=object(),  # type: ignore[arg-type]
    )

    monkeypatch.setattr(
        "whale.shared.source.opcua.reader.build_opcua_client_backend",
        lambda connection: backend,
    )
    reader = OpcUaSourceReader(_connection())
    monkeypatch.setattr(backend, "prepare_read", lambda addresses: plan)

    observed: dict[str, object] = {}

    async def _fake_read_prepared_values(prepared_plan: PreparedReadPlan) -> Batch:
        observed["plan"] = prepared_plan
        return Batch(
            changes=(),
            batch_observed_at=datetime(2026, 5, 15, tzinfo=UTC),
            client_received_at=datetime(2026, 5, 15, tzinfo=UTC),
            availability_status="VALID",
        )

    reader._read_prepared_values = _fake_read_prepared_values  # type: ignore[method-assign]  # noqa: SLF001

    batch = asyncio.run(reader.read(["s=IED001.LD0.WPPD1.TotW"], mode="value_only"))

    assert isinstance(batch, Batch)
    assert observed["plan"] is plan


@pytest.mark.unit
def test_full_batch_read_rejects_non_asyncua_data_values(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Full batch conversion should fail clearly when raw values lack asyncua metadata."""

    backend = AsyncuaOpcUaClientBackend(_connection())
    plan = AsyncuaPreparedReadPlan(
        node_paths=("ns=2;s=IED001.LD0.WPPD1.TotW",),
        nodes=(),
        read_params=object(),  # type: ignore[arg-type]
    )
    raw_result = RawOpcUaReadResult(
        ok=True,
        data_values=(object(),),
        response_timestamp=datetime(2026, 5, 15, tzinfo=UTC),
    )

    monkeypatch.setattr(
        "whale.shared.source.opcua.reader.build_opcua_client_backend",
        lambda connection: backend,
    )
    reader = OpcUaSourceReader(_connection())
    monkeypatch.setattr(backend, "read_prepared_raw", lambda prepared_plan: asyncio.sleep(0, result=raw_result))

    with pytest.raises(TypeError, match="full Batch read requires asyncua DataValue metadata"):
        asyncio.run(reader.read_prepared(plan, mode="full"))
