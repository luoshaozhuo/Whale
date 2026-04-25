"""SQLAlchemy ORM model for one substation asset."""

from __future__ import annotations

from sqlalchemy import Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from whale.ingest.framework.persistence.base import Base


class SubstationORM(Base):
    """Persist one substation asset such as a wind or solar plant."""

    __tablename__ = "substation"
    __table_args__ = ({"comment": "Substation or plant-level asset registry"},)

    id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
        autoincrement=True,
        comment="Primary key for one substation row",
    )
    name: Mapped[str] = mapped_column(
        String(255),
        unique=True,
        nullable=False,
        comment="Unique substation name",
    )
