"""IEC 61850 采集测点模板模块.

IED → LD → LN → DO 四层采集模板.
多个同型号设备共用同一 IED 模板.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import (
    JSON,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from whale.shared.persistence import Base


class IED(Base):
    """智能电子设备采集模板."""

    __tablename__ = "scada_ied"
    __table_args__ = {"comment": "IED 采集模板（IEC 61850）"}

    ied_id: Mapped[int] = mapped_column(
        Integer, primary_key=True, autoincrement=True, comment="IED主键"
    )
    ied_name: Mapped[str] = mapped_column(
        String(255), unique=True, nullable=False, comment="IED 模板名称"
    )
    protocol_type: Mapped[str] = mapped_column(
        String(64), nullable=False, comment="协议类型"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), comment="创建时间"
    )

    lds: Mapped[list["LD"]] = relationship(back_populates="ied", cascade="all, delete-orphan")


class LD(Base):
    """逻辑设备模板 — ld_name 使用英文资产类型标识."""

    __tablename__ = "scada_ld"
    __table_args__ = (
        UniqueConstraint("ied_id", "ld_name", name="uq_scada_ld_ied_name"),
        {"comment": "逻辑设备模板（IEC 61850 LD）"},
    )

    ld_id: Mapped[int] = mapped_column(
        Integer, primary_key=True, autoincrement=True, comment="LD主键"
    )
    ld_name: Mapped[str] = mapped_column(
        String(255), nullable=False, comment="LD名称（英文标识，如 WTG/MET/SUB）"
    )
    ied_id: Mapped[int] = mapped_column(
        ForeignKey("scada_ied.ied_id"), nullable=False, index=True, comment="所属IED"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), comment="创建时间"
    )

    ied: Mapped["IED"] = relationship(back_populates="lds")
    lns: Mapped[list["LN"]] = relationship(back_populates="ld", cascade="all, delete-orphan")


class LN(Base):
    """逻辑节点模板."""

    __tablename__ = "scada_ln"
    __table_args__ = (
        UniqueConstraint("ld_id", "ln_name", name="uq_scada_ln_ld_name"),
        {"comment": "逻辑节点模板（IEC 61850 LN）"},
    )

    ln_id: Mapped[int] = mapped_column(
        Integer, primary_key=True, autoincrement=True, comment="LN主键"
    )
    ln_name: Mapped[str] = mapped_column(
        String(255), nullable=False, comment="LN名称（WGEN/WTUR/MMXU等）"
    )
    ld_id: Mapped[int] = mapped_column(
        ForeignKey("scada_ld.ld_id"), nullable=False, index=True, comment="所属LD"
    )
    description: Mapped[Optional[str]] = mapped_column(
        String(512), nullable=True, comment="LN 中文说明（如 发电机信息/叶轮信息 等）"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), comment="创建时间"
    )

    ld: Mapped["LD"] = relationship(back_populates="lns")
    dos: Mapped[list["DO"]] = relationship(back_populates="ln", cascade="all, delete-orphan")


class DO(Base):
    """数据对象模板 — 含数据类型ID、单位、约束表达式、显示名称."""

    __tablename__ = "scada_do"
    __table_args__ = (
        UniqueConstraint("ln_id", "do_name", name="uq_scada_do_ln_name"),
        {"comment": "数据对象模板（IEC 61850 DO）"},
    )

    do_id: Mapped[int] = mapped_column(
        Integer, primary_key=True, autoincrement=True, comment="DO主键"
    )
    do_name: Mapped[str] = mapped_column(
        String(255), nullable=False, comment="DO名称（TotW/WSpd等），即 OPC UA node_path 末段"
    )
    ln_id: Mapped[int] = mapped_column(
        ForeignKey("scada_ln.ln_id"), nullable=False, index=True, comment="所属LN"
    )
    cdc: Mapped[Optional[str]] = mapped_column(
        String(64), nullable=True, comment="公共数据类（MV/SPS/ACT等）"
    )
    fc: Mapped[Optional[str]] = mapped_column(
        String(64), nullable=True, comment="功能约束（ST/MX/CF/DC等）"
    )
    data_type_id: Mapped[int] = mapped_column(
        ForeignKey("scada_data_type.data_type_id"), nullable=False, index=True,
        comment="关联 SCADA 数据类型"
    )
    unit: Mapped[Optional[str]] = mapped_column(
        String(64), nullable=True, comment="单位"
    )
    constraint_expr: Mapped[Optional[str]] = mapped_column(
        String(255), nullable=True,
        comment="数据约束表达式，如 BETWEEN 0 1500 / >= 0 / IN running stopped fault / NONE",
    )
    display_name: Mapped[Optional[str]] = mapped_column(
        String(255), nullable=True, comment="显示名称（中文描述，不含引用标准）"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), comment="创建时间"
    )

    ln: Mapped["LN"] = relationship(back_populates="dos")
    do_states: Mapped[list["DOState"]] = relationship(back_populates="do")
    data_type: Mapped["ScadaDataType"] = relationship(back_populates="dos")


# ══════════════════════════════════════════════════════════════════════
# SCADA 数据类型（IEC 61850-7-2 Basic Types）
# ══════════════════════════════════════════════════════════════════════


class ScadaDataType(Base):
    """IEC 61850-7-2 / GB/T 30966.2 基本数据类型."""

    __tablename__ = "scada_data_type"
    __table_args__ = {"comment": "SCADA 基本数据类型（IEC 61850-7-2）"}

    data_type_id: Mapped[int] = mapped_column(
        Integer, primary_key=True, autoincrement=True, comment="类型主键"
    )
    type_name: Mapped[str] = mapped_column(
        String(64), unique=True, nullable=False, comment="类型名称（BOOLEAN/INT32/FLOAT64等）"
    )
    description: Mapped[Optional[str]] = mapped_column(
        String(255), nullable=True, comment="中文说明"
    )
    encoding: Mapped[Optional[str]] = mapped_column(
        String(128), nullable=True, comment="编码方式（IEEE 754 / Two's complement / ASCII等）"
    )
    size_bits: Mapped[Optional[int]] = mapped_column(
        Integer, nullable=True, comment="位宽"
    )
    range_min: Mapped[Optional[str]] = mapped_column(
        String(64), nullable=True, comment="值域下限"
    )
    range_max: Mapped[Optional[str]] = mapped_column(
        String(64), nullable=True, comment="值域上限"
    )

    dos: Mapped[list["DO"]] = relationship(back_populates="data_type")


# ══════════════════════════════════════════════════════════════════════
# CDC / FC 枚举说明表
# ══════════════════════════════════════════════════════════════════════


class CDCDict(Base):
    """公共数据类（CDC）枚举说明."""

    __tablename__ = "scada_cdc_dict"
    __table_args__ = {"comment": "IEC 61850 CDC 公共数据类说明"}

    cdc_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    cdc_code: Mapped[str] = mapped_column(
        String(8), unique=True, nullable=False, comment="CDC 代码"
    )
    cdc_name: Mapped[str] = mapped_column(
        String(64), nullable=False, comment="CDC 英文全称"
    )
    description: Mapped[Optional[str]] = mapped_column(
        String(512), nullable=True, comment="中文说明"
    )


class FCDict(Base):
    """功能约束（FC）枚举说明."""

    __tablename__ = "scada_fc_dict"
    __table_args__ = {"comment": "IEC 61850 FC 功能约束说明"}

    fc_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    fc_code: Mapped[str] = mapped_column(
        String(8), unique=True, nullable=False, comment="FC 代码"
    )
    fc_name: Mapped[str] = mapped_column(
        String(64), nullable=False, comment="FC 英文全称"
    )
    description: Mapped[Optional[str]] = mapped_column(
        String(512), nullable=True, comment="中文说明"
    )


# ══════════════════════════════════════════════════════════════════════
# 测点扁平视图（IED → LD → LN → DO）
# ══════════════════════════════════════════════════════════════════════

MEASUREMENT_POINT_VIEW_SQL = """
CREATE VIEW IF NOT EXISTS v_measurement_point AS
SELECT
    do.do_id,
    do.do_name,
    COALESCE(cdc_dict.description, do.cdc)  AS cdc,
    COALESCE(fc_dict.description, do.fc)    AS fc,
    sdt.type_name                            AS data_type,
    do.unit,
    do.constraint_expr,
    do.display_name,

    ln.ln_id,
    ln.ln_name,
    ln.description                           AS ln_description,

    ld.ld_id,
    ld.ld_name,

    ied.ied_id,
    ied.ied_name,
    ied.protocol_type

FROM scada_do        do
JOIN scada_ln        ln  ON ln.ln_id = do.ln_id
JOIN scada_ld        ld  ON ld.ld_id = ln.ld_id
JOIN scada_ied       ied ON ied.ied_id = ld.ied_id
JOIN scada_data_type sdt ON sdt.data_type_id = do.data_type_id
LEFT JOIN scada_cdc_dict cdc_dict ON cdc_dict.cdc_code = do.cdc
LEFT JOIN scada_fc_dict fc_dict   ON fc_dict.fc_code = do.fc
"""


class MeasurementPointView(Base):
    """测点扁平视图 — IED → LD → LN → DO 四层全路径展开."""

    __tablename__ = "v_measurement_point"
    __table_args__ = {"comment": "测点扁平视图"}

    do_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    do_name: Mapped[str] = mapped_column(String(255))
    cdc: Mapped[Optional[str]] = mapped_column(String(512))
    fc: Mapped[Optional[str]] = mapped_column(String(512))
    data_type: Mapped[str] = mapped_column(String(64))
    unit: Mapped[Optional[str]] = mapped_column(String(64))
    constraint_expr: Mapped[Optional[str]] = mapped_column(String(255))
    display_name: Mapped[Optional[str]] = mapped_column(String(255))

    ln_id: Mapped[int] = mapped_column(Integer)
    ln_name: Mapped[str] = mapped_column(String(255))
    ln_description: Mapped[Optional[str]] = mapped_column(String(512))

    ld_id: Mapped[int] = mapped_column(Integer)
    ld_name: Mapped[str] = mapped_column(String(255))

    ied_id: Mapped[int] = mapped_column(Integer)
    ied_name: Mapped[str] = mapped_column(String(255))
    protocol_type: Mapped[str] = mapped_column(String(64))


# ══════════════════════════════════════════════════════════════════════
# 资产型号详情视图（通用）
# ══════════════════════════════════════════════════════════════════════

ASSET_MODEL_DETAIL_VIEW_SQL = """
CREATE VIEW IF NOT EXISTS v_asset_model_detail AS
SELECT
    am.model_id,
    at.asset_type_id,
    at.asset_type_name,
    am.model_name,
    am.manufacturer,
    am.specifications,
    aa.attribute_name,
    aa.description                           AS attr_desc,
    sdt.type_name                            AS data_type,
    aa.unit                                  AS attr_unit,
    aa.constraint_expr,
    json_extract(am.specifications,
        '$.' || aa.attribute_name)           AS attr_value
FROM asset_model am
JOIN asset_type        at  ON at.asset_type_id = am.asset_type_id
LEFT JOIN asset_attribute aa  ON aa.asset_type_id = am.asset_type_id
LEFT JOIN scada_data_type sdt ON sdt.data_type_id = aa.data_type_id
"""


class AssetModelDetailView(Base):
    __tablename__ = "v_asset_model_detail"
    __table_args__ = {"comment": "资产型号详情视图（通用）"}

    model_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    asset_type_id: Mapped[int] = mapped_column(Integer)
    asset_type_name: Mapped[str] = mapped_column(String(255))
    model_name: Mapped[str] = mapped_column(String(255))
    manufacturer: Mapped[Optional[str]] = mapped_column(String(255))
    specifications: Mapped[dict] = mapped_column(JSON)
    attribute_name: Mapped[Optional[str]] = mapped_column(String(255))
    attr_desc: Mapped[Optional[str]] = mapped_column(String(255))
    data_type: Mapped[Optional[str]] = mapped_column(String(64))
    attr_unit: Mapped[Optional[str]] = mapped_column(String(64))
    constraint_expr: Mapped[Optional[str]] = mapped_column(String(255))
    attr_value: Mapped[Optional[str]] = mapped_column(String(1024))


# ══════════════════════════════════════════════════════════════════════
# 部件型号详情视图（通用）
# ══════════════════════════════════════════════════════════════════════

COMPONENT_MODEL_DETAIL_VIEW_SQL = """
CREATE VIEW IF NOT EXISTS v_component_model_detail AS
SELECT
    cm.model_id,
    ct.component_type_id,
    ct.component_type_name,
    cm.model_name,
    cm.manufacturer,
    cm.specifications,
    ca.attribute_name,
    ca.description                           AS attr_desc,
    sdt.type_name                            AS data_type,
    ca.unit                                  AS attr_unit,
    ca.constraint_expr,
    json_extract(cm.specifications,
        '$.' || ca.attribute_name)           AS attr_value
FROM component_model cm
JOIN component_type         ct  ON ct.component_type_id = cm.component_type_id
LEFT JOIN component_attribute ca ON ca.component_type_id = cm.component_type_id
LEFT JOIN scada_data_type    sdt ON sdt.data_type_id = ca.data_type_id
"""


class ComponentModelDetailView(Base):
    __tablename__ = "v_component_model_detail"
    __table_args__ = {"comment": "部件型号详情视图（通用）"}

    model_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    component_type_id: Mapped[int] = mapped_column(Integer)
    component_type_name: Mapped[str] = mapped_column(String(255))
    model_name: Mapped[str] = mapped_column(String(255))
    manufacturer: Mapped[Optional[str]] = mapped_column(String(255))
    specifications: Mapped[dict] = mapped_column(JSON)
    attribute_name: Mapped[Optional[str]] = mapped_column(String(255))
    attr_desc: Mapped[Optional[str]] = mapped_column(String(255))
    data_type: Mapped[Optional[str]] = mapped_column(String(64))
    attr_unit: Mapped[Optional[str]] = mapped_column(String(64))
    constraint_expr: Mapped[Optional[str]] = mapped_column(String(255))
    attr_value: Mapped[Optional[str]] = mapped_column(String(1024))


# ══════════════════════════════════════════════════════════════════════
# DO 状态详情视图（asset_code + do_name 替换 ID）
# ══════════════════════════════════════════════════════════════════════

ACQ_DO_STATE_DETAIL_VIEW_SQL = """
CREATE VIEW IF NOT EXISTS v_acq_do_state_detail AS
SELECT
    ads.do_state_id,
    ads.task_id,
    ai.asset_code,
    do.do_name,
    do.display_name,
    ads.value,
    ads.source_observed_at,
    ads.received_at,
    ads.updated_at
FROM acq_do_state ads
JOIN asset_instance ai ON ai.asset_instance_id = ads.asset_instance_id
JOIN scada_do       do ON do.do_id = ads.do_id
"""


class AcqDOStateDetailView(Base):
    __tablename__ = "v_acq_do_state_detail"
    __table_args__ = {"comment": "DO状态详情视图（含 asset_code/do_name）"}

    do_state_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    task_id: Mapped[int] = mapped_column(Integer)
    asset_code: Mapped[str] = mapped_column(String(255))
    do_name: Mapped[str] = mapped_column(String(255))
    display_name: Mapped[Optional[str]] = mapped_column(String(255))
    value: Mapped[str] = mapped_column(String)
    source_observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


# Remove view tables from metadata so SQLAlchemy won't try to CREATE TABLE
Base.metadata.remove(MeasurementPointView.__table__)
Base.metadata.remove(AssetModelDetailView.__table__)
Base.metadata.remove(ComponentModelDetailView.__table__)
Base.metadata.remove(AcqDOStateDetailView.__table__)
