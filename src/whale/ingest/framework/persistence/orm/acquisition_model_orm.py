"""SQLAlchemy ORM model for acquisition-model headers."""

from __future__ import annotations

from sqlalchemy import JSON, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from whale.ingest.framework.persistence.base import Base


class AcquisitionModelORM(Base):
    """Persist one acquisition model header with protocol and version."""

    __tablename__ = "acquisition_model"
    __table_args__ = (
        UniqueConstraint(
            "model_id",
            "model_version",
            name="uq_acquisition_model_identity",
        ),
        {"comment": "Acquisition model headers by model id and version"},
    )

    id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
        autoincrement=True,
        comment="Primary key for one acquisition-model header row",
    )
    model_id: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        index=True,
        comment="Logical acquisition model identifier",
    )
    model_version: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        comment="Version of the acquisition model definition",
    )
    protocol: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        comment="Protocol used by this acquisition model version",
    )
    model_params: Mapped[dict[str, str | int | float | bool | None]] = mapped_column(
        JSON,
        nullable=False,
        default=dict,
        comment="Model-level protocol parameters stored as structured JSON",
    )
