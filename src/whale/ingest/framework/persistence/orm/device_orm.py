"""SQLAlchemy ORM model for one device asset."""

from __future__ import annotations

from sqlalchemy import Boolean, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from whale.ingest.framework.persistence.base import Base


class DeviceORM(Base):
    """Persist one device asset within a substation."""

    __tablename__ = "device"
    __table_args__ = (
        UniqueConstraint(
            "substation_id",
            "device_code",
            name="uq_device_substation_device_code",
        ),
        {"comment": "Physical or logical devices available for acquisition"},
    )

    id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
        autoincrement=True,
        comment="Primary key for one device row",
    )
    substation_id: Mapped[int] = mapped_column(
        ForeignKey("substation.id"),
        nullable=False,
        index=True,
        comment="Owning substation identifier",
    )
    device_code: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        comment="Business device code within the owning substation",
    )
    device_model: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
        comment="Device model or manufacturer model code",
    )
    line_number: Mapped[str | None] = mapped_column(
        String(64),
        nullable=True,
        comment="Collection-line identifier for the device",
    )
    enabled: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        comment="Whether this device is enabled for task assignment",
    )
