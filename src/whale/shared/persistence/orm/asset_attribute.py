"""Asset attribute definition module.

Describes what attributes each asset type has — meaning, data type, unit, constraints.
Referenced by v_asset_model_detail to extract values from AssetModel.specifications JSON.
"""

from __future__ import annotations

from typing import Optional

from sqlalchemy import ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from whale.shared.persistence import Base


class AssetAttribute(Base):
    """Per-type asset attribute metadata."""

    __tablename__ = "asset_attribute"
    __table_args__ = {"comment": "资产型号属性定义（名称、含义、数据类型、单位、约束）"}

    attribute_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    asset_type_id: Mapped[int] = mapped_column(
        ForeignKey("asset_type.asset_type_id"), nullable=False, index=True, comment="所属资产类型"
    )
    attribute_name: Mapped[str] = mapped_column(
        String(255), nullable=False, comment="属性名（JSON key，如 rated_power_kw）"
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

    asset_type: Mapped["AssetType"] = relationship(back_populates="attributes")
    data_type: Mapped["ScadaDataType"] = relationship()
