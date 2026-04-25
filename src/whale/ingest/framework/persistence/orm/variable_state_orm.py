"""SQLAlchemy ORM model for latest variable states."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from whale.ingest.framework.persistence.base import Base


class VariableStateORM(Base):
    """Persist the latest cached state for one device variable."""

    __tablename__ = "variable_state"
    __table_args__ = (
        UniqueConstraint(
            "device_code",
            "model_id",
            "variable_key",
            name="uq_variable_state_device_model_variable",
        ),
        {"comment": "Latest cached variable state"},
    )

    id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
        autoincrement=True,
        comment="Surrogate row identifier",
    )

    device_code: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        comment="Business device code",
    )
    model_id: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        comment="Business acquisition-model identifier",
    )
    variable_key: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        comment="Logical variable key within the acquisition model",
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
