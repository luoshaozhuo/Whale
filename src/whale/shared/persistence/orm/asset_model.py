"""资产型号库模块.

每张表通过 asset_type_id 关联 AssetType，字段对齐产品铭牌参数.
"""

from __future__ import annotations

from typing import Optional

from sqlalchemy import Float, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from whale.shared.persistence import Base
from whale.shared.persistence.orm.asset import AssetType


# ══════════════════════════════════════════════════════════════════════
# 风机型号
# ══════════════════════════════════════════════════════════════════════


class WindTurbineModel(Base):
    """风机型号表 — 字段对齐产品铭牌."""

    __tablename__ = "asset_wind_turbine_model"
    __table_args__ = {"comment": "风机型号（铭牌参数）"}

    model_id: Mapped[int] = mapped_column(
        Integer, primary_key=True, autoincrement=True, comment="型号主键"
    )
    asset_type_id: Mapped[int] = mapped_column(
        ForeignKey("asset_type.asset_type_id"), nullable=False, index=True, comment="关联资产类型"
    )
    model_name: Mapped[str] = mapped_column(String(255), nullable=False, comment="型号名称")
    rated_power_kw: Mapped[Optional[float]] = mapped_column(
        Float, nullable=True, comment="额定功率（kW）"
    )
    cut_in_wind_speed_m_s: Mapped[Optional[float]] = mapped_column(
        Float, nullable=True, comment="切入风速（m/s）"
    )
    cut_out_wind_speed_m_s: Mapped[Optional[float]] = mapped_column(
        Float, nullable=True, comment="切出风速（m/s）"
    )
    rated_wind_speed_m_s: Mapped[Optional[float]] = mapped_column(
        Float, nullable=True, comment="额定风速（m/s）"
    )
    survival_wind_speed_m_s: Mapped[Optional[float]] = mapped_column(
        Float, nullable=True, comment="极限生存风速（m/s）"
    )
    rotor_diameter_m: Mapped[Optional[float]] = mapped_column(
        Float, nullable=True, comment="风轮直径（m）"
    )
    hub_height_m: Mapped[Optional[float]] = mapped_column(
        Float, nullable=True, comment="轮毂高度（m）"
    )
    rated_voltage_v: Mapped[Optional[int]] = mapped_column(
        Integer, nullable=True, comment="额定电压（V）"
    )
    frequency_hz: Mapped[Optional[float]] = mapped_column(
        Float, nullable=True, comment="额定频率（Hz，50/60）"
    )
    min_operating_temp_c: Mapped[Optional[float]] = mapped_column(
        Float, nullable=True, comment="最低运行温度（℃）"
    )
    max_operating_temp_c: Mapped[Optional[float]] = mapped_column(
        Float, nullable=True, comment="最高运行温度（℃）"
    )
    survival_min_temp_c: Mapped[Optional[float]] = mapped_column(
        Float, nullable=True, comment="最低生存温度（℃）"
    )
    survival_max_temp_c: Mapped[Optional[float]] = mapped_column(
        Float, nullable=True, comment="最高生存温度（℃）"
    )
    design_life_year: Mapped[Optional[int]] = mapped_column(
        Integer, nullable=True, comment="设计寿命（年）"
    )
    wind_class: Mapped[Optional[str]] = mapped_column(
        String(16), nullable=True, comment="风区等级（IEC I/II/III/S/T）"
    )
    manufacturer: Mapped[Optional[str]] = mapped_column(
        String(255), nullable=True, comment="制造商"
    )

    asset_type: Mapped["AssetType"] = relationship(back_populates="wind_turbine_models")


# ══════════════════════════════════════════════════════════════════════
# 光伏逆变器型号
# ══════════════════════════════════════════════════════════════════════


class PVInverterModel(Base):
    """光伏逆变器型号表 — 字段对齐产品铭牌."""

    __tablename__ = "asset_pv_inverter_model"
    __table_args__ = {"comment": "光伏逆变器型号（铭牌参数）"}

    model_id: Mapped[int] = mapped_column(
        Integer, primary_key=True, autoincrement=True, comment="型号主键"
    )
    asset_type_id: Mapped[int] = mapped_column(
        ForeignKey("asset_type.asset_type_id"), nullable=False, index=True, comment="关联资产类型"
    )
    model_name: Mapped[str] = mapped_column(String(255), nullable=False, comment="型号名称")
    rated_power_kw: Mapped[Optional[float]] = mapped_column(
        Float, nullable=True, comment="额定输出功率（kW）"
    )
    max_input_voltage_v: Mapped[Optional[int]] = mapped_column(
        Integer, nullable=True, comment="最大直流输入电压（V）"
    )
    mppt_voltage_min_v: Mapped[Optional[int]] = mapped_column(
        Integer, nullable=True, comment="MPPT 电压范围下限（V）"
    )
    mppt_voltage_max_v: Mapped[Optional[int]] = mapped_column(
        Integer, nullable=True, comment="MPPT 电压范围上限（V）"
    )
    rated_output_voltage_v: Mapped[Optional[int]] = mapped_column(
        Integer, nullable=True, comment="额定交流输出电压（V）"
    )
    rated_output_frequency_hz: Mapped[Optional[float]] = mapped_column(
        Float, nullable=True, comment="额定输出频率（Hz）"
    )
    max_efficiency: Mapped[Optional[float]] = mapped_column(
        Float, nullable=True, comment="最大转换效率"
    )
    mppt_count: Mapped[Optional[int]] = mapped_column(
        Integer, nullable=True, comment="MPPT 路数"
    )
    protection_rating: Mapped[Optional[str]] = mapped_column(
        String(16), nullable=True, comment="防护等级（IP65等）"
    )
    operating_temp_min_c: Mapped[Optional[float]] = mapped_column(
        Float, nullable=True, comment="最低工作温度（℃）"
    )
    operating_temp_max_c: Mapped[Optional[float]] = mapped_column(
        Float, nullable=True, comment="最高工作温度（℃）"
    )
    manufacturer: Mapped[Optional[str]] = mapped_column(
        String(255), nullable=True, comment="制造商"
    )

    asset_type: Mapped["AssetType"] = relationship(back_populates="pv_inverter_models")


# ══════════════════════════════════════════════════════════════════════
# 光伏组件型号
# ══════════════════════════════════════════════════════════════════════


class PVPanelModel(Base):
    """光伏组件型号表 — 字段对齐产品铭牌."""

    __tablename__ = "asset_pv_panel_model"
    __table_args__ = {"comment": "光伏组件型号（铭牌参数）"}

    model_id: Mapped[int] = mapped_column(
        Integer, primary_key=True, autoincrement=True, comment="型号主键"
    )
    asset_type_id: Mapped[int] = mapped_column(
        ForeignKey("asset_type.asset_type_id"), nullable=False, index=True, comment="关联资产类型"
    )
    model_name: Mapped[str] = mapped_column(String(255), nullable=False, comment="型号名称")
    peak_power_wp: Mapped[Optional[float]] = mapped_column(
        Float, nullable=True, comment="峰值功率（Wp）"
    )
    open_circuit_voltage_v: Mapped[Optional[float]] = mapped_column(
        Float, nullable=True, comment="开路电压（V）"
    )
    short_circuit_current_a: Mapped[Optional[float]] = mapped_column(
        Float, nullable=True, comment="短路电流（A）"
    )
    voltage_at_pmax_v: Mapped[Optional[float]] = mapped_column(
        Float, nullable=True, comment="最大功率点电压（V）"
    )
    current_at_pmax_a: Mapped[Optional[float]] = mapped_column(
        Float, nullable=True, comment="最大功率点电流（A）"
    )
    module_efficiency: Mapped[Optional[float]] = mapped_column(
        Float, nullable=True, comment="组件转换效率"
    )
    temperature_coefficient_pmax: Mapped[Optional[float]] = mapped_column(
        Float, nullable=True, comment="功率温度系数（%/℃）"
    )
    cell_type: Mapped[Optional[str]] = mapped_column(
        String(128), nullable=True, comment="电池类型（单晶P型/N型/HJT等）"
    )
    cell_count: Mapped[Optional[int]] = mapped_column(
        Integer, nullable=True, comment="电池片数量"
    )
    dimensions_mm: Mapped[Optional[str]] = mapped_column(
        String(64), nullable=True, comment="外形尺寸（mm）"
    )
    weight_kg: Mapped[Optional[float]] = mapped_column(
        Float, nullable=True, comment="重量（kg）"
    )
    manufacturer: Mapped[Optional[str]] = mapped_column(
        String(255), nullable=True, comment="制造商"
    )

    asset_type: Mapped["AssetType"] = relationship(back_populates="pv_panel_models")


# ══════════════════════════════════════════════════════════════════════
# 储能变流器型号
# ══════════════════════════════════════════════════════════════════════


class PCSModel(Base):
    """储能变流器（PCS）型号表 — 字段对齐产品铭牌."""

    __tablename__ = "asset_pcs_model"
    __table_args__ = {"comment": "储能变流器型号（铭牌参数）"}

    model_id: Mapped[int] = mapped_column(
        Integer, primary_key=True, autoincrement=True, comment="型号主键"
    )
    asset_type_id: Mapped[int] = mapped_column(
        ForeignKey("asset_type.asset_type_id"), nullable=False, index=True, comment="关联资产类型"
    )
    model_name: Mapped[str] = mapped_column(String(255), nullable=False, comment="型号名称")
    rated_power_kw: Mapped[Optional[float]] = mapped_column(
        Float, nullable=True, comment="额定功率（kW）"
    )
    rated_apparent_power_kva: Mapped[Optional[float]] = mapped_column(
        Float, nullable=True, comment="额定视在功率（kVA）"
    )
    dc_voltage_min_v: Mapped[Optional[int]] = mapped_column(
        Integer, nullable=True, comment="直流电压下限（V）"
    )
    dc_voltage_max_v: Mapped[Optional[int]] = mapped_column(
        Integer, nullable=True, comment="直流电压上限（V）"
    )
    ac_rated_voltage_v: Mapped[Optional[int]] = mapped_column(
        Integer, nullable=True, comment="交流额定电压（V）"
    )
    ac_rated_frequency_hz: Mapped[Optional[float]] = mapped_column(
        Float, nullable=True, comment="交流额定频率（Hz）"
    )
    max_efficiency: Mapped[Optional[float]] = mapped_column(
        Float, nullable=True, comment="最大转换效率"
    )
    response_time_ms: Mapped[Optional[int]] = mapped_column(
        Integer, nullable=True, comment="响应时间（ms）"
    )
    cooling_method: Mapped[Optional[str]] = mapped_column(
        String(64), nullable=True, comment="冷却方式（风冷/液冷）"
    )
    operating_temp_min_c: Mapped[Optional[float]] = mapped_column(
        Float, nullable=True, comment="最低工作温度（℃）"
    )
    operating_temp_max_c: Mapped[Optional[float]] = mapped_column(
        Float, nullable=True, comment="最高工作温度（℃）"
    )
    protection_rating: Mapped[Optional[str]] = mapped_column(
        String(16), nullable=True, comment="防护等级"
    )
    manufacturer: Mapped[Optional[str]] = mapped_column(
        String(255), nullable=True, comment="制造商"
    )

    asset_type: Mapped["AssetType"] = relationship(back_populates="pcs_models")


# ══════════════════════════════════════════════════════════════════════
# 储能电池系统型号
# ══════════════════════════════════════════════════════════════════════


class BatterySystemModel(Base):
    """电池系统型号表 — 字段对齐产品铭牌."""

    __tablename__ = "asset_battery_system_model"
    __table_args__ = {"comment": "电池系统型号（铭牌参数）"}

    model_id: Mapped[int] = mapped_column(
        Integer, primary_key=True, autoincrement=True, comment="型号主键"
    )
    asset_type_id: Mapped[int] = mapped_column(
        ForeignKey("asset_type.asset_type_id"), nullable=False, index=True, comment="关联资产类型"
    )
    model_name: Mapped[str] = mapped_column(String(255), nullable=False, comment="型号名称")
    rated_energy_kwh: Mapped[Optional[float]] = mapped_column(
        Float, nullable=True, comment="额定能量（kWh）"
    )
    rated_power_kw: Mapped[Optional[float]] = mapped_column(
        Float, nullable=True, comment="额定功率（kW）"
    )
    nominal_voltage_v: Mapped[Optional[float]] = mapped_column(
        Float, nullable=True, comment="标称电压（V）"
    )
    operating_voltage_min_v: Mapped[Optional[float]] = mapped_column(
        Float, nullable=True, comment="工作电压下限（V）"
    )
    operating_voltage_max_v: Mapped[Optional[float]] = mapped_column(
        Float, nullable=True, comment="工作电压上限（V）"
    )
    chemistry_type: Mapped[Optional[str]] = mapped_column(
        String(64), nullable=True, comment="电芯化学体系（LFP/NMC/LTO等）"
    )
    max_charge_c_rate: Mapped[Optional[float]] = mapped_column(
        Float, nullable=True, comment="最大充电倍率（C）"
    )
    max_discharge_c_rate: Mapped[Optional[float]] = mapped_column(
        Float, nullable=True, comment="最大放电倍率（C）"
    )
    round_trip_efficiency: Mapped[Optional[float]] = mapped_column(
        Float, nullable=True, comment="充放电往返效率"
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
    manufacturer: Mapped[Optional[str]] = mapped_column(
        String(255), nullable=True, comment="制造商"
    )

    asset_type: Mapped["AssetType"] = relationship(back_populates="battery_system_models")


# ══════════════════════════════════════════════════════════════════════
# 变压器型号
# ══════════════════════════════════════════════════════════════════════


class TransformerModel(Base):
    """变压器型号表 — 字段对齐产品铭牌."""

    __tablename__ = "asset_transformer_model"
    __table_args__ = {"comment": "变压器型号（铭牌参数）"}

    model_id: Mapped[int] = mapped_column(
        Integer, primary_key=True, autoincrement=True, comment="型号主键"
    )
    asset_type_id: Mapped[int] = mapped_column(
        ForeignKey("asset_type.asset_type_id"), nullable=False, index=True, comment="关联资产类型"
    )
    model_name: Mapped[str] = mapped_column(String(255), nullable=False, comment="型号名称")
    rated_capacity_kva: Mapped[Optional[float]] = mapped_column(
        Float, nullable=True, comment="额定容量（kVA）"
    )
    primary_voltage_kv: Mapped[Optional[float]] = mapped_column(
        Float, nullable=True, comment="一次侧额定电压（kV）"
    )
    secondary_voltage_kv: Mapped[Optional[float]] = mapped_column(
        Float, nullable=True, comment="二次侧额定电压（kV）"
    )
    vector_group: Mapped[Optional[str]] = mapped_column(
        String(16), nullable=True, comment="联结组别（Dyn11/YNd11等）"
    )
    impedance_percent: Mapped[Optional[float]] = mapped_column(
        Float, nullable=True, comment="阻抗电压百分比"
    )
    cooling_method: Mapped[Optional[str]] = mapped_column(
        String(64), nullable=True, comment="冷却方式（ONAN/ONAF/强迫油循环等）"
    )
    tap_changer_type: Mapped[Optional[str]] = mapped_column(
        String(64), nullable=True, comment="调压方式（有载/无载）"
    )
    manufacturer: Mapped[Optional[str]] = mapped_column(
        String(255), nullable=True, comment="制造商"
    )

    asset_type: Mapped["AssetType"] = relationship(back_populates="transformer_models")


# ══════════════════════════════════════════════════════════════════════
# SVG 无功补偿型号
# ══════════════════════════════════════════════════════════════════════


class SVGModel(Base):
    """SVG 静止无功发生器型号表 — 字段对齐产品铭牌."""

    __tablename__ = "asset_svg_model"
    __table_args__ = {"comment": "SVG无功补偿型号（铭牌参数）"}

    model_id: Mapped[int] = mapped_column(
        Integer, primary_key=True, autoincrement=True, comment="型号主键"
    )
    asset_type_id: Mapped[int] = mapped_column(
        ForeignKey("asset_type.asset_type_id"), nullable=False, index=True, comment="关联资产类型"
    )
    model_name: Mapped[str] = mapped_column(String(255), nullable=False, comment="型号名称")
    rated_capacity_kvar: Mapped[Optional[float]] = mapped_column(
        Float, nullable=True, comment="额定容量（kvar）"
    )
    rated_voltage_kv: Mapped[Optional[float]] = mapped_column(
        Float, nullable=True, comment="额定电压（kV）"
    )
    rated_frequency_hz: Mapped[Optional[float]] = mapped_column(
        Float, nullable=True, comment="额定频率（Hz）"
    )
    response_time_ms: Mapped[Optional[int]] = mapped_column(
        Integer, nullable=True, comment="响应时间（ms）"
    )
    cooling_method: Mapped[Optional[str]] = mapped_column(
        String(64), nullable=True, comment="冷却方式（风冷/水冷）"
    )
    harmonic_compensation: Mapped[Optional[str]] = mapped_column(
        String(64), nullable=True, comment="谐波补偿能力（如 2~25次）"
    )
    operating_temp_min_c: Mapped[Optional[float]] = mapped_column(
        Float, nullable=True, comment="最低工作温度（℃）"
    )
    operating_temp_max_c: Mapped[Optional[float]] = mapped_column(
        Float, nullable=True, comment="最高工作温度（℃）"
    )
    manufacturer: Mapped[Optional[str]] = mapped_column(
        String(255), nullable=True, comment="制造商"
    )

    asset_type: Mapped["AssetType"] = relationship(back_populates="svg_models")
