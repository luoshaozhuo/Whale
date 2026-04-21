"""SQLAlchemy ORM model for OPC UA connection configuration."""

from __future__ import annotations

from sqlalchemy import Boolean, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from whale.ingest.framework.persistence.base import Base


class OpcUaClientConnectionORM(Base):
    """Persist one OPC UA client connection row."""

    __tablename__ = "opcua_client_connections"
    __table_args__ = {"comment": "OPC UA client connection configuration"}

    id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
        autoincrement=True,
        comment="Primary key for OPC UA connection configuration",
    )
    name: Mapped[str] = mapped_column(
        String(255),
        unique=True,
        nullable=False,
        comment="Human-readable source name used as a configuration key",
    )
    endpoint: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        comment="OPC UA server endpoint URL",
    )
    security_policy: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        comment="Configured OPC UA security policy",
    )
    security_mode: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        comment="Configured OPC UA security mode",
    )
    update_interval_ms: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        comment="Requested source update interval in milliseconds",
    )
    enabled: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        comment="Whether this OPC UA connection is enabled for acquisition",
    )
