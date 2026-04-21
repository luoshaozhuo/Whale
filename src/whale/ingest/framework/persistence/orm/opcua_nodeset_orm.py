"""SQLAlchemy ORM models for OPC UA NodeSet metadata."""

from __future__ import annotations

from sqlalchemy import Boolean, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from whale.ingest.framework.persistence.base import Base


class NamespaceUriORM(Base):
    """Persist one NodeSet namespace URI."""

    __tablename__ = "opcua_nodeset_namespace"
    __table_args__ = {"comment": "NodeSet namespace URI catalog"}

    id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
        autoincrement=True,
        comment="Primary key for a namespace URI row",
    )
    uri: Mapped[str] = mapped_column(
        Text,
        unique=True,
        nullable=False,
        comment="Namespace URI declared by the NodeSet",
    )
    sort_order: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        comment="Stable display order for namespace URIs",
    )


class AliasORM(Base):
    """Persist one NodeSet alias entry."""

    __tablename__ = "opcua_nodeset_aliases"
    __table_args__ = {"comment": "NodeSet alias definitions"}

    id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
        autoincrement=True,
        comment="Primary key for an alias row",
    )
    alias: Mapped[str] = mapped_column(
        String(255),
        unique=True,
        nullable=False,
        comment="Alias name defined by the NodeSet",
    )
    target_node_id: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        comment="Target node id referenced by the alias",
    )


class UaObjectTypeORM(Base):
    """Persist one UAObjectType node."""

    __tablename__ = "opcua_nodeset_object_types"
    __table_args__ = {"comment": "UAObjectType nodes from the NodeSet catalog"}

    id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
        autoincrement=True,
        comment="Primary key for an object type row",
    )
    node_id: Mapped[str] = mapped_column(
        String(255),
        unique=True,
        nullable=False,
        comment="Node id of the UAObjectType",
    )
    browse_name: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        comment="Browse name of the UAObjectType",
    )
    display_name: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        comment="Display name of the UAObjectType",
    )
    is_abstract: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        comment="Whether the UAObjectType is abstract",
    )


class UaObjectORM(Base):
    """Persist one UAObject node."""

    __tablename__ = "opcua_nodeset_objects"
    __table_args__ = {"comment": "UAObject nodes from the NodeSet catalog"}

    id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
        autoincrement=True,
        comment="Primary key for a UAObject row",
    )
    node_id: Mapped[str] = mapped_column(
        String(255),
        unique=True,
        nullable=False,
        comment="Node id of the UAObject",
    )
    browse_name: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        comment="Browse name of the UAObject",
    )
    display_name: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        comment="Display name of the UAObject",
    )
    parent_node_id: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
        comment="Parent node id of the UAObject if present",
    )
    type_definition: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
        comment="Type definition node id of the UAObject if present",
    )


class UaVariableORM(Base):
    """Persist one UAVariable node."""

    __tablename__ = "opcua_nodeset_variables"
    __table_args__ = {"comment": "UAVariable nodes from the NodeSet catalog"}

    id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
        autoincrement=True,
        comment="Primary key for a UAVariable row",
    )
    node_id: Mapped[str] = mapped_column(
        String(255),
        unique=True,
        nullable=False,
        comment="Node id of the UAVariable",
    )
    browse_name: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        comment="Browse name of the UAVariable",
    )
    display_name: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        comment="Display name of the UAVariable",
    )
    parent_node_id: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        comment="Parent node id of the UAVariable",
    )
    data_type: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
        comment="Data type node id of the UAVariable if present",
    )
    value_rank: Mapped[str | None] = mapped_column(
        String(64),
        nullable=True,
        comment="Value rank of the UAVariable if present",
    )
    initial_value_text: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        comment="Serialized initial value text of the UAVariable if present",
    )


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
        {"comment": "Reference edges between NodeSet nodes"},
    )

    id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
        autoincrement=True,
        comment="Primary key for a reference row",
    )
    source_node_id: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        comment="Source node id of the reference",
    )
    source_node_class: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        comment="Source node class of the reference",
    )
    reference_type: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        comment="Reference type browse name or node id",
    )
    is_forward: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        comment="Whether the reference direction is forward",
    )
    target_node_id: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        comment="Target node id of the reference",
    )
