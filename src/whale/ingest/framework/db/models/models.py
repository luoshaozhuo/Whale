"""SQLAlchemy ORM models for OPC UA configuration storage."""

from __future__ import annotations

from typing import Optional

from sqlalchemy import Boolean, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from whale.ingest.framework.db.base import Base


class NamespaceUriORM(Base):
    """Persist one NodeSet namespace URI."""

    __tablename__ = "opcua_nodeset_namespace"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    uri: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False)


class AliasORM(Base):
    """Persist one NodeSet alias entry."""

    __tablename__ = "opcua_nodeset_aliases"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    alias: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    target_node_id: Mapped[str] = mapped_column(String(255), nullable=False)


class UaObjectTypeORM(Base):
    """Persist one UAObjectType node."""

    __tablename__ = "opcua_nodeset_object_types"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    node_id: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    browse_name: Mapped[str] = mapped_column(String(255), nullable=False)
    display_name: Mapped[str] = mapped_column(String(255), nullable=False)
    is_abstract: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)


class UaObjectORM(Base):
    """Persist one UAObject node."""

    __tablename__ = "opcua_nodeset_objects"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    node_id: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    browse_name: Mapped[str] = mapped_column(String(255), nullable=False)
    display_name: Mapped[str] = mapped_column(String(255), nullable=False)
    parent_node_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    type_definition: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)


class UaVariableORM(Base):
    """Persist one UAVariable node."""

    __tablename__ = "opcua_nodeset_variables"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    node_id: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    browse_name: Mapped[str] = mapped_column(String(255), nullable=False)
    display_name: Mapped[str] = mapped_column(String(255), nullable=False)
    parent_node_id: Mapped[str] = mapped_column(String(255), nullable=False)
    data_type: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    value_rank: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    initial_value_text: Mapped[Optional[str]] = mapped_column(Text, nullable=True)


class UaReferenceORM(Base):
    """Persist one relation between NodeSet nodes."""

    __tablename__ = "opcua_nodeset_references"
    __table_args__ = (
        UniqueConstraint(
            "source_node_id",
            "source_node_class",
            "reference_type",
            "is_forward",
            "target_node_id",
            name="uq_opcua_reference_identity",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    source_node_id: Mapped[str] = mapped_column(String(255), nullable=False)
    source_node_class: Mapped[str] = mapped_column(String(64), nullable=False)
    reference_type: Mapped[str] = mapped_column(String(255), nullable=False)
    is_forward: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    target_node_id: Mapped[str] = mapped_column(String(255), nullable=False)


class OpcUaClientConnectionORM(Base):
    """Persist one OPC UA client connection row."""

    __tablename__ = "opcua_client_connections"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    endpoint: Mapped[str] = mapped_column(String(255), nullable=False)
    security_policy: Mapped[str] = mapped_column(String(255), nullable=False)
    security_mode: Mapped[str] = mapped_column(String(255), nullable=False)
    update_interval_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
