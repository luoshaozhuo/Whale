"""资产与部件实体管理模块."""

from __future__ import annotations

from datetime import date, datetime
from typing import Optional

from sqlalchemy import (
    Date,
    DateTime,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from whale.shared.persistence import Base


class AssetType(Base):
    __tablename__ = "asset_type"
    __table_args__ = {"comment": "资产类型"}

    asset_type_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    asset_type_name: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, comment="类型名称")
    category: Mapped[str] = mapped_column(String(255), nullable=False, comment="类别")
    description: Mapped[Optional[str]] = mapped_column(String(1024), nullable=True, comment="描述")

    asset_instances: Mapped[list["AssetInstance"]] = relationship(back_populates="asset_type")
    boms: Mapped[list["AssetBOM"]] = relationship(back_populates="asset_type")
    wind_turbine_models: Mapped[list["WindTurbineModel"]] = relationship(back_populates="asset_type")
    pv_inverter_models: Mapped[list["PVInverterModel"]] = relationship(back_populates="asset_type")
    pv_panel_models: Mapped[list["PVPanelModel"]] = relationship(back_populates="asset_type")
    pcs_models: Mapped[list["PCSModel"]] = relationship(back_populates="asset_type")
    battery_system_models: Mapped[list["BatterySystemModel"]] = relationship(back_populates="asset_type")
    transformer_models: Mapped[list["TransformerModel"]] = relationship(back_populates="asset_type")
    svg_models: Mapped[list["SVGModel"]] = relationship(back_populates="asset_type")


class ComponentType(Base):
    __tablename__ = "component_type"
    __table_args__ = {"comment": "部件类型"}

    component_type_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    component_type_name: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, comment="部件类型名称")
    description: Mapped[Optional[str]] = mapped_column(String(1024), nullable=True, comment="描述")

    component_instances: Mapped[list["ComponentInstance"]] = relationship(back_populates="component_type")
    boms: Mapped[list["AssetBOM"]] = relationship(back_populates="component_type")
    blade_models: Mapped[list["BladeModel"]] = relationship(back_populates="component_type")
    tower_models: Mapped[list["TowerModel"]] = relationship(back_populates="component_type")
    gearbox_models: Mapped[list["GearboxModel"]] = relationship(back_populates="component_type")
    generator_models: Mapped[list["GeneratorModel"]] = relationship(back_populates="component_type")
    pitch_system_models: Mapped[list["PitchSystemModel"]] = relationship(back_populates="component_type")
    tracker_models: Mapped[list["TrackerModel"]] = relationship(back_populates="component_type")
    combiner_box_models: Mapped[list["CombinerBoxModel"]] = relationship(back_populates="component_type")
    battery_cell_models: Mapped[list["BatteryCellModel"]] = relationship(back_populates="component_type")
    bms_models: Mapped[list["BMSModel"]] = relationship(back_populates="component_type")
    thermal_management_models: Mapped[list["ThermalManagementModel"]] = relationship(back_populates="component_type")


class AssetInstance(Base):
    __tablename__ = "asset_instance"
    __table_args__ = {"comment": "资产实例"}

    asset_instance_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    asset_code: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, comment="资产编号")
    asset_type_id: Mapped[int] = mapped_column(
        ForeignKey("asset_type.asset_type_id"), nullable=False, index=True, comment="资产类型"
    )
    model_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, comment="型号ID（多态引用）")
    installation_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True, comment="安装日期")
    location: Mapped[Optional[str]] = mapped_column(String(512), nullable=True, comment="安装位置")
    org_id: Mapped[int] = mapped_column(
        ForeignKey("org_unit.org_id"), nullable=False, index=True, comment="所属组织"
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())

    asset_type: Mapped["AssetType"] = relationship(back_populates="asset_instances")
    org: Mapped["Organization"] = relationship(back_populates="asset_instances")
    component_instances: Mapped[list["ComponentInstance"]] = relationship(back_populates="asset_instance")
    acquisition_tasks: Mapped[list["AcquisitionTask"]] = relationship(back_populates="asset_instance")


class ComponentInstance(Base):
    __tablename__ = "component_instance"
    __table_args__ = {"comment": "部件实例"}

    component_instance_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    component_type_id: Mapped[int] = mapped_column(
        ForeignKey("component_type.component_type_id"), nullable=False, index=True, comment="部件类型"
    )
    component_model_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, comment="部件型号ID（多态引用）")
    asset_instance_id: Mapped[int] = mapped_column(
        ForeignKey("asset_instance.asset_instance_id"), nullable=False, index=True, comment="所属资产实例"
    )
    installation_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True, comment="安装日期")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())

    component_type: Mapped["ComponentType"] = relationship(back_populates="component_instances")
    asset_instance: Mapped["AssetInstance"] = relationship(back_populates="component_instances")


class AssetBOM(Base):
    __tablename__ = "asset_bom"
    __table_args__ = (
        UniqueConstraint("asset_type_id", "asset_model_id", "component_type_id", "component_model_id", name="uq_asset_bom"),
        {"comment": "资产型号→部件型号 BOM"},
    )

    bom_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    asset_type_id: Mapped[int] = mapped_column(ForeignKey("asset_type.asset_type_id"), nullable=False, index=True)
    asset_model_id: Mapped[int] = mapped_column(Integer, nullable=False, comment="资产型号ID（多态引用）")
    component_type_id: Mapped[int] = mapped_column(ForeignKey("component_type.component_type_id"), nullable=False, index=True)
    component_model_id: Mapped[int] = mapped_column(Integer, nullable=False, comment="部件型号ID（多态引用）")
    quantity: Mapped[int] = mapped_column(Integer, nullable=False, default=1, comment="单台用量")

    asset_type: Mapped["AssetType"] = relationship(back_populates="boms")
    component_type: Mapped["ComponentType"] = relationship(back_populates="boms")


# ══════════════════════════════════════════════════════════════════════
# 风机 BOM 视图
# ══════════════════════════════════════════════════════════════════════

WIND_TURBINE_BOM_VIEW_SQL = """
CREATE VIEW IF NOT EXISTS v_wind_turbine_bom AS
SELECT
    ab.bom_id,
    at.asset_type_id,
    at.asset_type_name,
    ab.asset_model_id,
    wt.model_name           AS asset_model_name,
    ct.component_type_id,
    ct.component_type_name,
    ab.component_model_id,
    ab.quantity
FROM asset_bom ab
JOIN asset_type               at ON at.asset_type_id = ab.asset_type_id
JOIN asset_wind_turbine_model wt ON wt.model_id = ab.asset_model_id
JOIN component_type           ct ON ct.component_type_id = ab.component_type_id
"""


class WindTurbineBOMView(Base):
    __tablename__ = "v_wind_turbine_bom"
    __table_args__ = {"comment": "风机型号部件 BOM 扁平视图"}

    bom_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    asset_type_id: Mapped[int] = mapped_column(Integer)
    asset_type_name: Mapped[str] = mapped_column(String(255))
    asset_model_id: Mapped[int] = mapped_column(Integer)
    asset_model_name: Mapped[str] = mapped_column(String(255))
    component_type_id: Mapped[int] = mapped_column(Integer)
    component_type_name: Mapped[str] = mapped_column(String(255))
    component_model_id: Mapped[int] = mapped_column(Integer)
    quantity: Mapped[int] = mapped_column(Integer)


Base.metadata.remove(WindTurbineBOMView.__table__)
