"""Unit tests for the relational outbox snapshot publisher."""

from __future__ import annotations

from collections.abc import Generator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from whale.ingest.adapters.message.relational_outbox_message_publisher import (
    RelationalOutboxMessagePublisher,
)
from whale.ingest.framework.persistence.base import Base
from whale.ingest.framework.persistence.orm.state_snapshot_outbox_orm import (
    StateSnapshotOutboxORM,
)
from whale.ingest.usecases.dtos.state_snapshot_message import StateSnapshotMessage


def _build_message() -> StateSnapshotMessage:
    """Build one minimal snapshot message for publisher tests."""
    snapshot_at = datetime(2026, 4, 25, 10, 30, tzinfo=UTC)
    return StateSnapshotMessage(
        message_id="msg-001",
        schema_version="v1",
        message_type="STATE_SNAPSHOT",
        source_module="ingest",
        snapshot_id="snapshot-001",
        snapshot_at=snapshot_at,
        item_count=0,
        items=[],
        trace_id="trace-001",
    )


def test_publish_snapshot_persists_one_outbox_row(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Write one snapshot message into the relational outbox table."""
    engine = create_engine(f"sqlite:///{tmp_path / 'outbox.sqlite'}")
    Base.metadata.create_all(bind=engine)
    session_factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)

    @contextmanager
    def _session_scope() -> Generator[Session, None, None]:
        session = session_factory()
        try:
            yield session
        finally:
            session.close()

    monkeypatch.setattr(
        "whale.ingest.adapters.message.relational_outbox_message_publisher.session_scope",
        _session_scope,
    )

    publisher = RelationalOutboxMessagePublisher()

    result = publisher.publish_snapshot(_build_message())

    with session_factory() as session:
        row = session.scalar(select(StateSnapshotOutboxORM))

    assert row is not None
    assert result.pipeline_name == "relational_outbox"
    assert result.success is True
    assert row.message_id == "msg-001"
    assert row.snapshot_id == "snapshot-001"
    assert row.schema_version == "v1"
    assert row.message_type == "STATE_SNAPSHOT"
