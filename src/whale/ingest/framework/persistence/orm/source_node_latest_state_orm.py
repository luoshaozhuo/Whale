"""SQLAlchemy ORM model for latest cached ingest node states."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from whale.ingest.framework.persistence.base import Base


class SourceNodeLatestStateORM(Base):
    """Persist the latest cached node state for one source item."""

    __tablename__ = "source_node_latest_state"
    __table_args__ = (
        UniqueConstraint(
            "source_id",
            "node_key",
            name="uq_source_node_latest_state_source_node_key",
        ),
        {"comment": "Latest cached ingest node state by source and node key"},
    )

    id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
        autoincrement=True,
        comment="Primary key for one latest-state cache row",
    )
    source_id: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        index=True,
        comment="Stable source identifier",
    )
    node_key: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        comment="Logical node key inside the source",
    )
    node_id: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        comment="Concrete protocol node address",
    )
    value: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        comment="Serialized latest node value",
    )
    quality: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
        comment="Source-side quality or status text if available",
    )
    observed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        comment="Timestamp reported for the source observation",
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
        comment="Timestamp when the latest-state cache row was last updated",
    )
