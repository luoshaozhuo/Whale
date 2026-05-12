"""SQLite-backed latest-state cache for ingest.

本模块提供 SQLite 版本的 latest-state cache。

设计约定：
- latest-state cache 以 LD/source 为状态视图单位；
- 一个 LD 有一个统一的可用性状态和状态时间；
- 点位值按 batch 写入；
- 点位内部保留 source_timestamp / server_timestamp / client_sequence；
- 点位内部版本只用于乱序保护和诊断，不作为业务主时间；
- mark_alive() 只刷新链路活性，不改变点位值；
- mark_unavailable() 只降级 LD 状态，不删除最后有效值；
- read_snapshot() 返回 LD 级快照，不兼容旧的单点快照结构。
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import (
    Column,
    DateTime,
    Integer,
    String,
    Text,
    UniqueConstraint,
    select,
)
from sqlalchemy.orm import DeclarativeBase

from whale.ingest.framework.persistence.session import session_scope
from whale.ingest.ports.state.source_state_cache_port import SourceStateCachePort
from whale.ingest.ports.state.source_state_snapshot_reader_port import (
    CachedNodeValue,
    CachedSourceState,
    SourceStateSnapshotReaderPort,
)
from whale.ingest.usecases.dtos.acquired_node_state import (
    AcquiredNodeStateBatch,
    AcquiredNodeValue,
)
from whale.shared.utils.time import ensure_utc, max_datetime


class _CacheBase(DeclarativeBase):
    """Private declarative base for SQLite latest-state cache tables."""


class _LdStateRow(_CacheBase):
    """LD/source 级 latest-state 元信息。"""

    __tablename__ = "ld_state"

    ld_name = Column(String(255), primary_key=True)
    source_id = Column(String(255), nullable=False)

    availability_status = Column(String(32), nullable=False, default="UNKNOWN")
    unavailable_reason = Column(Text, nullable=True)

    batch_observed_at = Column(DateTime(timezone=True), nullable=True)
    client_received_at = Column(DateTime(timezone=True), nullable=True)
    client_processed_at = Column(DateTime(timezone=True), nullable=True)

    last_alive_at = Column(DateTime(timezone=True), nullable=True)
    last_value_updated_at = Column(DateTime(timezone=True), nullable=True)
    state_updated_at = Column(DateTime(timezone=True), nullable=False)


class _VariableStateRow(_CacheBase):
    """点位 latest-state 行。"""

    __tablename__ = "variable_state"
    __table_args__ = (
        UniqueConstraint(
            "ld_name",
            "variable_key",
            name="uq_variable_state_ld_variable",
        ),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)

    ld_name = Column(String(255), nullable=False, index=True)
    source_id = Column(String(255), nullable=False)
    variable_key = Column(String(255), nullable=False)

    value = Column(Text, nullable=False)
    quality = Column(String(128), nullable=True)

    batch_observed_at = Column(DateTime(timezone=True), nullable=False)
    client_received_at = Column(DateTime(timezone=True), nullable=False)
    client_processed_at = Column(DateTime(timezone=True), nullable=False)

    source_timestamp = Column(DateTime(timezone=True), nullable=True)
    server_timestamp = Column(DateTime(timezone=True), nullable=True)
    client_sequence = Column(Integer, nullable=True)

    availability_status = Column(String(32), nullable=False, default="VALID")
    updated_at = Column(DateTime(timezone=True), nullable=False)


class SqliteSourceStateCache(SourceStateCachePort, SourceStateSnapshotReaderPort):
    """Persist and read the local latest-state cache from SQLite."""

    def __init__(self) -> None:
        """Ensure cache tables exist."""

        with session_scope() as session:
            _CacheBase.metadata.create_all(bind=session.get_bind(), checkfirst=True)

    def update(
        self,
        *,
        ld_name: str,
        batch: AcquiredNodeStateBatch,
    ) -> int:
        """按 batch 刷新一个 LD/source 的 latest-state。"""

        if batch.is_empty():
            return 0

        now = datetime.now(tz=UTC)
        updated_count = 0

        with session_scope() as session:
            ld_state = session.get(_LdStateRow, ld_name)
            if ld_state is None:
                ld_state = _LdStateRow(
                    ld_name=ld_name,
                    source_id=batch.source_id,
                    availability_status=batch.availability_status,
                    unavailable_reason=None,
                    batch_observed_at=batch.batch_observed_at,
                    client_received_at=batch.client_received_at,
                    client_processed_at=batch.client_processed_at,
                    last_alive_at=batch.client_processed_at,
                    last_value_updated_at=batch.client_processed_at,
                    state_updated_at=now,
                )
                session.add(ld_state)
            else:
                ld_state.source_id = batch.source_id
                ld_state.availability_status = batch.availability_status
                ld_state.unavailable_reason = None
                ld_state.batch_observed_at = max_datetime(
                    ld_state.batch_observed_at,
                    batch.batch_observed_at,
                )
                ld_state.client_received_at = batch.client_received_at
                ld_state.client_processed_at = batch.client_processed_at
                ld_state.last_alive_at = max_datetime(
                    ld_state.last_alive_at,
                    batch.client_processed_at,
                )
                ld_state.last_value_updated_at = max_datetime(
                    ld_state.last_value_updated_at,
                    batch.client_processed_at,
                )
                ld_state.state_updated_at = now

            node_keys = [value.node_key for value in batch.values]
            existing_rows = {
                row.variable_key: row
                for row in session.scalars(
                    select(_VariableStateRow).where(
                        _VariableStateRow.ld_name == ld_name,
                        _VariableStateRow.variable_key.in_(node_keys),
                    )
                )
            }

            for value in batch.values:
                current_row = existing_rows.get(value.node_key)

                if current_row is not None and not _should_update_value(
                    incoming=value,
                    current=current_row,
                ):
                    continue

                if current_row is None:
                    session.add(
                        _VariableStateRow(
                            ld_name=ld_name,
                            source_id=batch.source_id,
                            variable_key=value.node_key,
                            value=value.value,
                            quality=value.quality,
                            batch_observed_at=batch.batch_observed_at,
                            client_received_at=batch.client_received_at,
                            client_processed_at=batch.client_processed_at,
                            source_timestamp=value.source_timestamp,
                            server_timestamp=value.server_timestamp,
                            client_sequence=value.client_sequence,
                            availability_status=batch.availability_status,
                            updated_at=now,
                        )
                    )
                else:
                    current_row.source_id = batch.source_id
                    current_row.value = value.value
                    current_row.quality = value.quality
                    current_row.batch_observed_at = batch.batch_observed_at
                    current_row.client_received_at = batch.client_received_at
                    current_row.client_processed_at = batch.client_processed_at
                    current_row.source_timestamp = value.source_timestamp
                    current_row.server_timestamp = value.server_timestamp
                    current_row.client_sequence = value.client_sequence
                    current_row.availability_status = batch.availability_status
                    current_row.updated_at = now

                updated_count += 1

            session.commit()

        return updated_count

    def mark_alive(
        self,
        *,
        ld_name: str,
        observed_at: datetime,
    ) -> None:
        """标记一个 LD/source 的采集链路仍然存活。"""

        now = datetime.now(tz=UTC)

        with session_scope() as session:
            ld_state = session.get(_LdStateRow, ld_name)
            if ld_state is None:
                ld_state = _LdStateRow(
                    ld_name=ld_name,
                    source_id=ld_name,
                    availability_status="UNKNOWN",
                    unavailable_reason=None,
                    batch_observed_at=None,
                    client_received_at=None,
                    client_processed_at=None,
                    last_alive_at=observed_at,
                    last_value_updated_at=None,
                    state_updated_at=now,
                )
                session.add(ld_state)
            else:
                ld_state.last_alive_at = max_datetime(
                    ld_state.last_alive_at,
                    observed_at,
                )
                if ld_state.availability_status in {"UNKNOWN", "STALE", "OFFLINE"}:
                    ld_state.availability_status = "VALID"
                    ld_state.unavailable_reason = None
                ld_state.state_updated_at = now

            session.commit()

    def mark_unavailable(
        self,
        *,
        ld_name: str,
        status: str,
        observed_at: datetime,
        reason: str | None = None,
    ) -> None:
        """将一个 LD/source 标记为不可用或降级状态。"""

        now = datetime.now(tz=UTC)

        with session_scope() as session:
            ld_state = session.get(_LdStateRow, ld_name)
            if ld_state is None:
                ld_state = _LdStateRow(
                    ld_name=ld_name,
                    source_id=ld_name,
                    availability_status=status,
                    unavailable_reason=reason,
                    batch_observed_at=None,
                    client_received_at=None,
                    client_processed_at=None,
                    last_alive_at=None,
                    last_value_updated_at=None,
                    state_updated_at=observed_at,
                )
                session.add(ld_state)
            else:
                ld_state.availability_status = status
                ld_state.unavailable_reason = reason
                ld_state.state_updated_at = max_datetime(
                    ld_state.state_updated_at,
                    observed_at,
                )

            for row in session.scalars(
                select(_VariableStateRow).where(_VariableStateRow.ld_name == ld_name)
            ):
                row.availability_status = status
                row.updated_at = now

            session.commit()

    def read_snapshot(self) -> list[CachedSourceState]:
        """读取全部 LD/source 的 latest-state 快照。"""

        with session_scope() as session:
            ld_rows = list(
                session.scalars(
                    select(_LdStateRow).order_by(_LdStateRow.ld_name)
                )
            )

            variable_rows_by_ld: dict[str, list[_VariableStateRow]] = {
                ld_row.ld_name: [] for ld_row in ld_rows
            }

            variable_rows = list(
                session.scalars(
                    select(_VariableStateRow).order_by(
                        _VariableStateRow.ld_name,
                        _VariableStateRow.variable_key,
                    )
                )
            )

            for row in variable_rows:
                variable_rows_by_ld.setdefault(row.ld_name, []).append(row)

            return [
                CachedSourceState(
                    ld_name=ld_row.ld_name,
                    source_id=ld_row.source_id,
                    availability_status=ld_row.availability_status,
                    unavailable_reason=ld_row.unavailable_reason,
                    batch_observed_at=ld_row.batch_observed_at,
                    client_received_at=ld_row.client_received_at,
                    client_processed_at=ld_row.client_processed_at,
                    last_alive_at=ld_row.last_alive_at,
                    last_value_updated_at=ld_row.last_value_updated_at,
                    state_updated_at=ld_row.state_updated_at,
                    values=[
                        CachedNodeValue(
                            node_key=row.variable_key,
                            value=row.value,
                            quality=row.quality,
                            source_timestamp=row.source_timestamp,
                            server_timestamp=row.server_timestamp,
                            client_sequence=row.client_sequence,
                            updated_at=row.updated_at,
                        )
                        for row in variable_rows_by_ld.get(ld_row.ld_name, [])
                    ],
                )
                for ld_row in ld_rows
            ]


def _should_update_value(
    *,
    incoming: AcquiredNodeValue,
    current: _VariableStateRow,
) -> bool:
    """判断 incoming 点值是否允许覆盖当前点值。"""

    if incoming.server_timestamp is not None:
        if current.server_timestamp is None:
            return True
        return ensure_utc(incoming.server_timestamp) >= ensure_utc(
            current.server_timestamp
        )

    if incoming.client_sequence is not None:
        if current.client_sequence is None:
            return True
        return incoming.client_sequence >= current.client_sequence

    return True


