"""SQLAlchemy ORM model for source runtime scheduling configuration."""

from __future__ import annotations

from sqlalchemy import Boolean, CheckConstraint, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from whale.ingest.framework.persistence.base import Base


class SourceRuntimeConfigORM(Base):
    """Persist runtime scheduling configuration for one source."""

    __tablename__ = "source_runtime_config"
    __table_args__ = (
        CheckConstraint(
            "protocol IN ('opcua')",
            name="ck_source_runtime_config_protocol",
        ),
        CheckConstraint(
            "acquisition_mode IN ('ONCE', 'POLLING', 'SUBSCRIPTION')",
            name="ck_source_runtime_config_acquisition_mode",
        ),
        {"comment": "Source runtime scheduling configuration"},
    )

    source_id: Mapped[str] = mapped_column(
        String(255),
        primary_key=True,
        comment="Stable source identifier used by the ingest scheduler",
    )
    protocol: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        comment="Source protocol name. Allowed values: opcua",
    )
    acquisition_mode: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        comment="Source acquisition mode. Allowed values: ONCE, POLLING, SUBSCRIPTION",
    )
    interval_ms: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        comment="Scheduling interval in milliseconds for polling or loop checks",
    )
    enabled: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        comment="Whether this source is enabled for scheduler dispatch",
    )
