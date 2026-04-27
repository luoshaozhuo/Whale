"""SQLAlchemy ORM model for persisted state snapshot outbox messages."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from whale.ingest.framework.persistence.base import Base


class StateSnapshotOutboxORM(Base):
    """Persist one emitted state snapshot message in the relational outbox."""

    __tablename__ = "state_snapshot_outbox"
    __table_args__ = ({"comment": "Outbox rows for published ingest state snapshots"},)

    id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
        autoincrement=True,
        comment="Primary key for one outbox row",
    )
    message_id: Mapped[str] = mapped_column(
        String(255),
        unique=True,
        nullable=False,
        index=True,
        comment="Stable published message identifier",
    )
    snapshot_id: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        index=True,
        comment="Snapshot identifier carried by the published message",
    )
    schema_version: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        comment="Schema version carried by the published message",
    )
    message_type: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        comment="Message type carried by the published message",
    )
    payload: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        comment="Serialized JSON payload for the published message",
    )
    snapshot_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        comment="Snapshot timestamp carried by the published message",
    )
    published_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        comment="Timestamp when the outbox row was created",
    )
