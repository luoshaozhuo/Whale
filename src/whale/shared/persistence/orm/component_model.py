"""部件型号库模块.

每张表通过 component_type_id 关联 ComponentType，字段对齐部件铭牌/规格书参数.
"""

from __future__ import annotations

from typing import Optional

from sqlalchemy import Boolean, Float, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from whale.shared.persistence import Base
from whale.shared.persistence.orm.asset import ComponentType


# ══════════════════════════════════════════════════════════════════════
# 叶片型号
# ══════════════════════════════════════════════════════════════════════


class BladeModel(Base):
    __tablename__ = "component_blade_model"
    __table_args__ = {"comment": "风机叶片型号（规格书参数）"}

    model_id: Mapped[int] = mapped_column(
        Integer, primary_key=True, autoincrement=True, comment="型号主键"
    )
    component_type_id: Mapped[int] = mapped_column(
        ForeignKey("component_type.component_type_id"), nullable=False, index=True,
        comment="关联部件类型"
    )
    model_name: Mapped[str] = mapped_column(String(255), nullable=False, comment="型号名称")
    length_m: Mapped[Optional[float]] = mapped_column(Float, nullable=True, comment="叶片长度（m）")
    weight_kg: Mapped[Optional[float]] = mapped_column(Float, nullable=True, comment="重量（kg）")
    material: Mapped[Optional[str]] = mapped_column(
        String(255), nullable=True, comment="材料（玻璃纤维/碳纤维增强等）"
    )
    aerodynamic_profile: Mapped[Optional[str]] = mapped_column(
        String(64), nullable=True, comment="气动翼型系列"
    )
    suitable_rotor_diameter_m: Mapped[Optional[float]] = mapped_column(
        Float, nullable=True, comment="适配风轮直径范围（m）"
    )
    design_life_year: Mapped[Optional[int]] = mapped_column(
        Integer, nullable=True, comment="设计寿命（年）"
    )
    manufacturer: Mapped[Optional[str]] = mapped_column(
        String(255), nullable=True, comment="制造商"
    )

    component_type: Mapped["ComponentType"] = relationship(back_populates="blade_models")


# ══════════════════════════════════════════════════════════════════════
# 塔筒型号
# ══════════════════════════════════════════════════════════════════════


class TowerModel(Base):
    __tablename__ = "component_tower_model"
    __table_args__ = {"comment": "风机塔筒型号（规格书参数）"}

    model_id: Mapped[int] = mapped_column(
        Integer, primary_key=True, autoincrement=True, comment="型号主键"
    )
    component_type_id: Mapped[int] = mapped_column(
        ForeignKey("component_type.component_type_id"), nullable=False, index=True,
        comment="关联部件类型"
    )
    model_name: Mapped[str] = mapped_column(String(255), nullable=False, comment="型号名称")
    hub_height_m: Mapped[Optional[float]] = mapped_column(Float, nullable=True, comment="轮毂高度（m）")
    top_diameter_m: Mapped[Optional[float]] = mapped_column(Float, nullable=True, comment="顶部直径（m）")
    bottom_diameter_m: Mapped[Optional[float]] = mapped_column(
        Float, nullable=True, comment="底部直径（m）"
    )
    sections_count: Mapped[Optional[int]] = mapped_column(
        Integer, nullable=True, comment="分段数量"
    )
    material: Mapped[Optional[str]] = mapped_column(
        String(255), nullable=True, comment="材料（Q345/Q420/混凝土混合等）"
    )
    suitable_power_kw: Mapped[Optional[float]] = mapped_column(
        Float, nullable=True, comment="适配功率范围（kW）"
    )
    manufacturer: Mapped[Optional[str]] = mapped_column(
        String(255), nullable=True, comment="制造商"
    )

    component_type: Mapped["ComponentType"] = relationship(back_populates="tower_models")


# ══════════════════════════════════════════════════════════════════════
# 齿轮箱型号
# ══════════════════════════════════════════════════════════════════════


class GearboxModel(Base):
    __tablename__ = "component_gearbox_model"
    __table_args__ = {"comment": "风机齿轮箱型号（规格书参数）"}

    model_id: Mapped[int] = mapped_column(
        Integer, primary_key=True, autoincrement=True, comment="型号主键"
    )
    component_type_id: Mapped[int] = mapped_column(
        ForeignKey("component_type.component_type_id"), nullable=False, index=True,
        comment="关联部件类型"
    )
    model_name: Mapped[str] = mapped_column(String(255), nullable=False, comment="型号名称")
    rated_power_kw: Mapped[Optional[float]] = mapped_column(
        Float, nullable=True, comment="额定功率（kW）"
    )
    ratio: Mapped[Optional[float]] = mapped_column(Float, nullable=True, comment="传动比")
    input_rpm: Mapped[Optional[float]] = mapped_column(
        Float, nullable=True, comment="额定输入转速（rpm）"
    )
    output_rpm: Mapped[Optional[float]] = mapped_column(
        Float, nullable=True, comment="额定输出转速（rpm）"
    )
    stages_count: Mapped[Optional[int]] = mapped_column(
        Integer, nullable=True, comment="行星级+平行级级数"
    )
    weight_kg: Mapped[Optional[float]] = mapped_column(Float, nullable=True, comment="重量（kg）")
    design_life_year: Mapped[Optional[int]] = mapped_column(
        Integer, nullable=True, comment="设计寿命（年）"
    )
    manufacturer: Mapped[Optional[str]] = mapped_column(
        String(255), nullable=True, comment="制造商"
    )

    component_type: Mapped["ComponentType"] = relationship(back_populates="gearbox_models")


# ══════════════════════════════════════════════════════════════════════
# 发电机型号
# ══════════════════════════════════════════════════════════════════════


class GeneratorModel(Base):
    __tablename__ = "component_generator_model"
    __table_args__ = {"comment": "发电机型号（规格书参数）"}

    model_id: Mapped[int] = mapped_column(
        Integer, primary_key=True, autoincrement=True, comment="型号主键"
    )
    component_type_id: Mapped[int] = mapped_column(
        ForeignKey("component_type.component_type_id"), nullable=False, index=True,
        comment="关联部件类型"
    )
    model_name: Mapped[str] = mapped_column(String(255), nullable=False, comment="型号名称")
    rated_power_kw: Mapped[Optional[float]] = mapped_column(
        Float, nullable=True, comment="额定功率（kW）"
    )
    rated_voltage_v: Mapped[Optional[int]] = mapped_column(
        Integer, nullable=True, comment="额定电压（V）"
    )
    rated_rpm: Mapped[Optional[int]] = mapped_column(
        Integer, nullable=True, comment="额定转速（rpm）"
    )
    rated_frequency_hz: Mapped[Optional[float]] = mapped_column(
        Float, nullable=True, comment="额定频率（Hz）"
    )
    efficiency: Mapped[Optional[float]] = mapped_column(
        Float, nullable=True, comment="额定效率"
    )
    cooling_type: Mapped[Optional[str]] = mapped_column(
        String(64), nullable=True, comment="冷却方式（IC616/IC666/空水冷等）"
    )
    insulation_class: Mapped[Optional[str]] = mapped_column(
        String(8), nullable=True, comment="绝缘等级（F/H等）"
    )
    protection_rating: Mapped[Optional[str]] = mapped_column(
        String(16), nullable=True, comment="防护等级"
    )
    generator_type: Mapped[Optional[str]] = mapped_column(
        String(64), nullable=True, comment="发电机类型（永磁直驱/双馈异步/鼠笼异步等）"
    )
    manufacturer: Mapped[Optional[str]] = mapped_column(
        String(255), nullable=True, comment="制造商"
    )

    component_type: Mapped["ComponentType"] = relationship(back_populates="generator_models")


# ══════════════════════════════════════════════════════════════════════
# 变桨系统型号
# ══════════════════════════════════════════════════════════════════════


class PitchSystemModel(Base):
    __tablename__ = "component_pitch_system_model"
    __table_args__ = {"comment": "变桨系统型号（规格书参数）"}

    model_id: Mapped[int] = mapped_column(
        Integer, primary_key=True, autoincrement=True, comment="型号主键"
    )
    component_type_id: Mapped[int] = mapped_column(
        ForeignKey("component_type.component_type_id"), nullable=False, index=True,
        comment="关联部件类型"
    )
    model_name: Mapped[str] = mapped_column(String(255), nullable=False, comment="型号名称")
    actuation_type: Mapped[Optional[str]] = mapped_column(
        String(64), nullable=True, comment="驱动方式（电动/液压）"
    )
    response_time_ms: Mapped[Optional[int]] = mapped_column(
        Integer, nullable=True, comment="响应时间（ms）"
    )
    max_pitch_rate_deg_s: Mapped[Optional[float]] = mapped_column(
        Float, nullable=True, comment="最大变桨速率（°/s）"
    )
    redundancy: Mapped[Optional[str]] = mapped_column(
        String(128), nullable=True, comment="冗余配置（3轴独立+后备电源等）"
    )
    emergency_stop_time_ms: Mapped[Optional[int]] = mapped_column(
        Integer, nullable=True, comment="紧急顺桨时间（ms）"
    )
    manufacturer: Mapped[Optional[str]] = mapped_column(
        String(255), nullable=True, comment="制造商"
    )

    component_type: Mapped["ComponentType"] = relationship(back_populates="pitch_system_models")


# ══════════════════════════════════════════════════════════════════════
# 光伏跟踪支架型号
# ══════════════════════════════════════════════════════════════════════


class TrackerModel(Base):
    __tablename__ = "component_tracker_model"
    __table_args__ = {"comment": "光伏跟踪支架型号（规格书参数）"}

    model_id: Mapped[int] = mapped_column(
        Integer, primary_key=True, autoincrement=True, comment="型号主键"
    )
    component_type_id: Mapped[int] = mapped_column(
        ForeignKey("component_type.component_type_id"), nullable=False, index=True,
        comment="关联部件类型"
    )
    model_name: Mapped[str] = mapped_column(String(255), nullable=False, comment="型号名称")
    tracking_type: Mapped[Optional[str]] = mapped_column(
        String(64), nullable=True, comment="跟踪方式（单轴平单轴/双轴等）"
    )
    tracking_range_deg: Mapped[Optional[str]] = mapped_column(
        String(64), nullable=True, comment="跟踪角度范围"
    )
    suitable_module_count: Mapped[Optional[int]] = mapped_column(
        Integer, nullable=True, comment="适配组件数量"
    )
    drive_type: Mapped[Optional[str]] = mapped_column(
        String(64), nullable=True, comment="驱动方式（电动推杆/回转减速机等）"
    )
    wind_resistance_m_s: Mapped[Optional[float]] = mapped_column(
        Float, nullable=True, comment="设计抗风能力（m/s）"
    )
    manufacturer: Mapped[Optional[str]] = mapped_column(
        String(255), nullable=True, comment="制造商"
    )

    component_type: Mapped["ComponentType"] = relationship(back_populates="tracker_models")


# ══════════════════════════════════════════════════════════════════════
# 汇流箱型号
# ══════════════════════════════════════════════════════════════════════


class CombinerBoxModel(Base):
    __tablename__ = "component_combiner_box_model"
    __table_args__ = {"comment": "光伏汇流箱型号（规格书参数）"}

    model_id: Mapped[int] = mapped_column(
        Integer, primary_key=True, autoincrement=True, comment="型号主键"
    )
    component_type_id: Mapped[int] = mapped_column(
        ForeignKey("component_type.component_type_id"), nullable=False, index=True,
        comment="关联部件类型"
    )
    model_name: Mapped[str] = mapped_column(String(255), nullable=False, comment="型号名称")
    input_string_count: Mapped[Optional[int]] = mapped_column(
        Integer, nullable=True, comment="输入组串数"
    )
    max_input_voltage_v: Mapped[Optional[int]] = mapped_column(
        Integer, nullable=True, comment="最大输入电压（V）"
    )
    max_output_current_a: Mapped[Optional[float]] = mapped_column(
        Float, nullable=True, comment="最大输出电流（A）"
    )
    protection_rating: Mapped[Optional[str]] = mapped_column(
        String(16), nullable=True, comment="防护等级（IP65等）"
    )
    has_monitoring: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, comment="是否带监控功能"
    )
    manufacturer: Mapped[Optional[str]] = mapped_column(
        String(255), nullable=True, comment="制造商"
    )

    component_type: Mapped["ComponentType"] = relationship(back_populates="combiner_box_models")


# ══════════════════════════════════════════════════════════════════════
# 电池单体型号
# ══════════════════════════════════════════════════════════════════════


class BatteryCellModel(Base):
    __tablename__ = "component_battery_cell_model"
    __table_args__ = {"comment": "电池单体型号（规格书参数）"}

    model_id: Mapped[int] = mapped_column(
        Integer, primary_key=True, autoincrement=True, comment="型号主键"
    )
    component_type_id: Mapped[int] = mapped_column(
        ForeignKey("component_type.component_type_id"), nullable=False, index=True,
        comment="关联部件类型"
    )
    model_name: Mapped[str] = mapped_column(String(255), nullable=False, comment="型号名称")
    chemistry: Mapped[Optional[str]] = mapped_column(
        String(64), nullable=True, comment="化学体系（LFP/NMC/LTO/钠离子等）"
    )
    nominal_voltage_v: Mapped[Optional[float]] = mapped_column(
        Float, nullable=True, comment="标称电压（V）"
    )
    capacity_ah: Mapped[Optional[float]] = mapped_column(
        Float, nullable=True, comment="额定容量（Ah）"
    )
    energy_density_wh_kg: Mapped[Optional[float]] = mapped_column(
        Float, nullable=True, comment="质量能量密度（Wh/kg）"
    )
    max_charge_c_rate: Mapped[Optional[float]] = mapped_column(
        Float, nullable=True, comment="最大持续充电倍率（C）"
    )
    max_discharge_c_rate: Mapped[Optional[float]] = mapped_column(
        Float, nullable=True, comment="最大持续放电倍率（C）"
    )
    cycle_life: Mapped[Optional[int]] = mapped_column(
        Integer, nullable=True, comment="循环寿命（次，至80%SOH）"
    )
    operating_temp_min_c: Mapped[Optional[float]] = mapped_column(
        Float, nullable=True, comment="最低工作温度（℃）"
    )
    operating_temp_max_c: Mapped[Optional[float]] = mapped_column(
        Float, nullable=True, comment="最高工作温度（℃）"
    )
    form_factor: Mapped[Optional[str]] = mapped_column(
        String(64), nullable=True, comment="封装形式（方形铝壳/圆柱/软包等）"
    )
    manufacturer: Mapped[Optional[str]] = mapped_column(
        String(255), nullable=True, comment="制造商"
    )

    component_type: Mapped["ComponentType"] = relationship(back_populates="battery_cell_models")


# ══════════════════════════════════════════════════════════════════════
# BMS 型号
# ══════════════════════════════════════════════════════════════════════


class BMSModel(Base):
    __tablename__ = "component_bms_model"
    __table_args__ = {"comment": "电池管理系统（BMS）型号（规格书参数）"}

    model_id: Mapped[int] = mapped_column(
        Integer, primary_key=True, autoincrement=True, comment="型号主键"
    )
    component_type_id: Mapped[int] = mapped_column(
        ForeignKey("component_type.component_type_id"), nullable=False, index=True,
        comment="关联部件类型"
    )
    model_name: Mapped[str] = mapped_column(String(255), nullable=False, comment="型号名称")
    topology: Mapped[Optional[str]] = mapped_column(
        String(64), nullable=True, comment="拓扑架构（集中式/分布式/三级架构等）"
    )
    max_cell_series_count: Mapped[Optional[int]] = mapped_column(
        Integer, nullable=True, comment="最大串联电芯数"
    )
    balancing_method: Mapped[Optional[str]] = mapped_column(
        String(64), nullable=True, comment="均衡方式（被动/主动）"
    )
    balancing_current_a: Mapped[Optional[float]] = mapped_column(
        Float, nullable=True, comment="均衡电流（A）"
    )
    communication_protocol: Mapped[Optional[str]] = mapped_column(
        String(128), nullable=True, comment="通信协议（CAN/Modbus RTU/IEC61850等）"
    )
    voltage_accuracy_mv: Mapped[Optional[float]] = mapped_column(
        Float, nullable=True, comment="电压采集精度（mV）"
    )
    temperature_accuracy_c: Mapped[Optional[float]] = mapped_column(
        Float, nullable=True, comment="温度采集精度（℃）"
    )
    manufacturer: Mapped[Optional[str]] = mapped_column(
        String(255), nullable=True, comment="制造商"
    )

    component_type: Mapped["ComponentType"] = relationship(back_populates="bms_models")


# ══════════════════════════════════════════════════════════════════════
# 热管理系统型号
# ══════════════════════════════════════════════════════════════════════


class ThermalManagementModel(Base):
    __tablename__ = "component_thermal_management_model"
    __table_args__ = {"comment": "热管理系统型号（规格书参数）"}

    model_id: Mapped[int] = mapped_column(
        Integer, primary_key=True, autoincrement=True, comment="型号主键"
    )
    component_type_id: Mapped[int] = mapped_column(
        ForeignKey("component_type.component_type_id"), nullable=False, index=True,
        comment="关联部件类型"
    )
    model_name: Mapped[str] = mapped_column(String(255), nullable=False, comment="型号名称")
    cooling_type: Mapped[Optional[str]] = mapped_column(
        String(64), nullable=True, comment="冷却方式（液冷/风冷/相变/热管等）"
    )
    cooling_capacity_kw: Mapped[Optional[float]] = mapped_column(
        Float, nullable=True, comment="制冷量（kW）"
    )
    heating_capacity_kw: Mapped[Optional[float]] = mapped_column(
        Float, nullable=True, comment="制热量（kW，低温启动用）"
    )
    operating_temp_min_c: Mapped[Optional[float]] = mapped_column(
        Float, nullable=True, comment="最低工作环境温度（℃）"
    )
    operating_temp_max_c: Mapped[Optional[float]] = mapped_column(
        Float, nullable=True, comment="最高工作环境温度（℃）"
    )
    coolant_type: Mapped[Optional[str]] = mapped_column(
        String(64), nullable=True, comment="冷却介质（乙二醇溶液/制冷剂等）"
    )
    noise_level_db: Mapped[Optional[float]] = mapped_column(
        Float, nullable=True, comment="噪声等级（dB）"
    )
    manufacturer: Mapped[Optional[str]] = mapped_column(
        String(255), nullable=True, comment="制造商"
    )

    component_type: Mapped["ComponentType"] = relationship(
        back_populates="thermal_management_models"
    )
