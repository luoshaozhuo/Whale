"""SQLAlchemy ORM model for persisted ingest node states."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from whale.ingest.framework.persistence.base import Base


class SourceNodeStateORM(Base):
    """Persist one node observation collected by ingest.

    The table behaves as an append-only observation history. The ingest refresh
    mainline now writes latest state into `source_node_latest_state` instead of
    using this table as a cache.
    """

    __tablename__ = "source_node_state"
    __table_args__ = ({"comment": "Ingest node observations persisted by source"},)

    id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
        autoincrement=True,
        comment="Primary key for one persisted node observation",
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
        comment="Concrete OPC UA node id",
    )
    value: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        comment="Serialized node value",
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
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        comment="Timestamp when ingest persisted the observation",
    )
