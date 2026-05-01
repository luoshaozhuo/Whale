"""SQLAlchemy ORM model for acquisition tasks."""

from __future__ import annotations

from sqlalchemy import JSON, Boolean, CheckConstraint, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from whale.ingest.framework.persistence.base import Base


class AcquisitionTaskORM(Base):
    """Persist one acquisition task bound to a device and model."""

    __tablename__ = "acquisition_task"
    __table_args__ = (
        CheckConstraint(
            "acquisition_mode IN ('ONCE', 'POLLING', 'SUBSCRIPTION')",
            name="ck_acquisition_task_acquisition_mode",
        ),
        {"comment": "Acquisition tasks bound to devices and acquisition models"},
    )

    id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
        autoincrement=True,
        comment="Primary key for one acquisition task row",
    )
    device_id: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        index=True,
        comment="Target device identifier for the task",
    )
    model_id: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        comment="Referenced acquisition model identifier",
    )
    model_version: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        comment="Referenced acquisition model version",
    )
    protocol: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        comment="Protocol used by the current task connection",
    )
    acquisition_mode: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        comment="Task acquisition mode. Allowed values: ONCE, POLLING, SUBSCRIPTION",
    )
    interval_ms: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        comment="Scheduling interval in milliseconds for polling or loop checks",
    )
    host: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
        comment="Optional host used by the task connection",
    )
    port: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
        comment="Optional port used by the task connection",
    )
    username: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
        comment="Optional username used by the task connection",
    )
    password: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
        comment="Optional password used by the task connection",
    )
    connection_params: Mapped[dict[str, str | int | float | bool | None]] = mapped_column(
        JSON,
        nullable=False,
        default=dict,
        comment="Protocol-specific connection parameters stored as structured JSON",
    )
    enabled: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        comment="Whether this acquisition task is enabled for scheduler dispatch",
    )
