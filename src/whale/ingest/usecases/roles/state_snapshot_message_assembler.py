"""Assembler for turning cached state rows into published snapshot messages."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from uuid import uuid4

from whale.ingest.usecases.dtos.cached_source_state import CachedSourceState
from whale.ingest.usecases.dtos.state_snapshot_message import (
    StateSnapshotItem,
    StateSnapshotMessage,
)


class StateSnapshotMessageAssembler:
    """Assemble one publishable state snapshot message from cached rows."""

    def __init__(
        self,
        *,
        now_factory: Callable[[], datetime] | None = None,
        id_factory: Callable[[], str] | None = None,
    ) -> None:
        """Store deterministic factories used by tests and runtime."""
        self._now_factory = now_factory or (lambda: datetime.now(tz=UTC))
        self._id_factory = id_factory or (lambda: uuid4().hex)

    def assemble(
        self,
        snapshot: list[CachedSourceState],
    ) -> StateSnapshotMessage:
        """Build one full snapshot message from cached source-state rows."""
        snapshot_at = self._now_factory()
        message_id = self._id_factory()
        snapshot_id = self._id_factory()
        return StateSnapshotMessage(
            message_id=message_id,
            schema_version="v1",
            message_type="STATE_SNAPSHOT",
            source_module="ingest",
            snapshot_id=snapshot_id,
            snapshot_at=snapshot_at,
            item_count=len(snapshot),
            items=[self._build_item(row) for row in snapshot],
            trace_id=message_id,
            attributes={},
        )

    @staticmethod
    def _build_item(row: CachedSourceState) -> StateSnapshotItem:
        """Map one cached state row into one snapshot message item."""
        return StateSnapshotItem(
            station_id=row.station_id,
            device_id=None,
            device_code=row.device_code,
            model_id=row.model_id,
            variable_key=row.variable_key,
            value=row.value,
            value_type=None,
            quality_code=None,
            source_observed_at=row.source_observed_at,
            received_at=row.received_at,
            updated_at=row.updated_at,
        )
