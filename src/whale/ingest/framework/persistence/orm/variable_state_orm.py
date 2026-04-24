"""SQLAlchemy ORM model for latest variable states."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from whale.ingest.framework.persistence.base import Base


class VariableStateORM(Base):
    """Persist the latest cached state for one device variable."""

    __tablename__ = "variable_state"
    __table_args__ = ({"comment": "Latest cached variable state"},)

    device_code: Mapped[str] = mapped_column(
        String(255),
        primary_key=True,
        comment="Business device code",
    )
    model_id: Mapped[str] = mapped_column(
        String(255),
        primary_key=True,
        comment="Business acquisition-model identifier",
    )
    variable_key: Mapped[str] = mapped_column(
        String(255),
        primary_key=True,
        comment="Logical variable key within the acquisition model",
    )
    node_id: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        comment="Concrete protocol node address",
    )
    value: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        comment="Serialized latest variable value",
    )
    source_observed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        comment="Timestamp reported by the source for the current value",
    )
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        comment="Timestamp when ingest last received this variable update",
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
        comment="Timestamp when this cached state row was last updated locally",
    )
