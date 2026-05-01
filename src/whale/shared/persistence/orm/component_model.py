"""Unified component model table.

All component type models stored in a single table with type-specific parameters in JSON.
"""

from __future__ import annotations

from typing import Optional

from sqlalchemy import ForeignKey, Integer, JSON, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from whale.shared.persistence import Base
from whale.shared.persistence.orm.asset import ComponentType


class ComponentModel(Base):
    """统一部件型号表 — 共有字段 + JSON specifications."""

    __tablename__ = "component_model"
    __table_args__ = {"comment": "部件型号（共有字段 + JSON 特有参数）"}

    model_id: Mapped[int] = mapped_column(
        Integer, primary_key=True, autoincrement=True, comment="型号主键"
    )
    component_type_id: Mapped[int] = mapped_column(
        ForeignKey("component_type.component_type_id"), nullable=False, index=True, comment="关联部件类型"
    )
    model_name: Mapped[str] = mapped_column(String(255), nullable=False, comment="型号名称")
    manufacturer: Mapped[Optional[str]] = mapped_column(
        String(255), nullable=True, comment="制造商"
    )
    specifications: Mapped[dict] = mapped_column(
        JSON, nullable=False, default=dict,
        comment="类型特有技术参数（如叶片: {length_m, weight_kg, ...}）"
    )

    component_type: Mapped["ComponentType"] = relationship(back_populates="models")
