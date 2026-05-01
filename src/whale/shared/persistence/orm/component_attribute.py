"""Component attribute definition module.

Describes what attributes each component type has — meaning, data type, unit, constraints.
Referenced by v_component_model_detail to extract values from ComponentModel.specifications JSON.
"""

from __future__ import annotations

from typing import Optional

from sqlalchemy import ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from whale.shared.persistence import Base


class ComponentAttribute(Base):
    """Per-type component attribute metadata."""

    __tablename__ = "component_attribute"
    __table_args__ = {"comment": "部件型号属性定义（名称、含义、数据类型、单位、约束）"}

    attribute_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    component_type_id: Mapped[int] = mapped_column(
        ForeignKey("component_type.component_type_id"), nullable=False, index=True, comment="所属部件类型"
    )
    attribute_name: Mapped[str] = mapped_column(
        String(255), nullable=False, comment="属性名（JSON key，如 length_m）"
    )
    description: Mapped[Optional[str]] = mapped_column(
        String(255), nullable=True, comment="中文含义"
    )
    data_type_id: Mapped[int] = mapped_column(
        ForeignKey("scada_data_type.data_type_id"), nullable=False, index=True,
        comment="SCADA 数据类型"
    )
    unit: Mapped[Optional[str]] = mapped_column(String(64), nullable=True, comment="单位")
    constraint_expr: Mapped[Optional[str]] = mapped_column(
        String(255), nullable=True, comment="约束表达式"
    )

    component_type: Mapped["ComponentType"] = relationship(back_populates="attributes")
    data_type: Mapped["ScadaDataType"] = relationship()
