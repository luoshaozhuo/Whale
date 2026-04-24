"""SQLAlchemy ORM model for acquisition variables within one model."""

from __future__ import annotations

from sqlalchemy import JSON, Boolean, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from whale.ingest.framework.persistence.base import Base


class AcquisitionVariableORM(Base):
    """Persist one variable item belonging to one acquisition model."""

    __tablename__ = "acquisition_variable"
    __table_args__ = (
        UniqueConstraint(
            "model_id",
            "variable_key",
            name="uq_acquisition_variable_identity",
        ),
        {"comment": "Variables defined within one acquisition model"},
    )

    id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
        autoincrement=True,
        comment="Primary key for one acquisition-variable row",
    )
    model_id: Mapped[int] = mapped_column(
        ForeignKey("acquisition_model.id"),
        nullable=False,
        index=True,
        comment="Referenced acquisition-model header identifier",
    )
    variable_key: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        comment="Logical variable key exposed by the model",
    )
    locator: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        comment="Protocol-specific locator such as node id, path or register address",
    )
    locator_type: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
        comment="Optional locator type such as node_id, path or register",
    )
    display_name: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
        comment="Optional human-readable variable name",
    )
    variable_params: Mapped[dict[str, str | int | float | bool | None]] = mapped_column(
        JSON,
        nullable=False,
        default=dict,
        comment="Protocol-specific variable parameters stored as structured JSON",
    )
    sort_order: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        comment="Stable variable ordering within one model version",
    )
    enabled: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        comment="Whether this variable row is enabled for acquisition",
    )
