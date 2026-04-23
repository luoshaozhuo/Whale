"""SQLAlchemy ORM model for OPC UA source-item bindings."""

from __future__ import annotations

from sqlalchemy import Boolean, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from whale.ingest.framework.persistence.base import Base


class OpcUaSourceItemBindingORM(Base):
    """Persist one explicit binding between a source and one OPC UA item."""

    __tablename__ = "opcua_source_item_binding"
    __table_args__ = (
        UniqueConstraint(
            "source_id",
            "item_key",
            name="uq_opcua_source_item_binding_source_item_key",
        ),
        {"comment": "Explicit source-to-item bindings for OPC UA acquisition"},
    )

    id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
        autoincrement=True,
        comment="Primary key for one source-item binding row",
    )
    source_id: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        index=True,
        comment="Source identifier resolved from runtime configuration",
    )
    item_key: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        comment="Logical item key exposed to the acquisition request",
    )
    node_address: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        comment="Protocol-specific node address suffix or absolute node id",
    )
    namespace_uri: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
        comment="Optional namespace URI used to resolve the item address",
    )
    display_name: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
        comment="Optional human-readable item display name",
    )
    enabled: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        comment="Whether the bound item is enabled for acquisition",
    )
    sort_order: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        comment="Stable item ordering within one source binding list",
    )
