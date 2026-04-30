"""IEC 61850 采集测点模板模块.

IED → LD → LN → DO 四层采集模板.
多个同型号设备共用同一 IED 模板.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import (
    DateTime,
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
    """逻辑设备模板 — ld_name 使用资产类型名称."""

    __tablename__ = "scada_ld"
    __table_args__ = (
        UniqueConstraint("ied_id", "ld_name", name="uq_scada_ld_ied_name"),
        {"comment": "逻辑设备模板（IEC 61850 LD）"},
    )

    ld_id: Mapped[int] = mapped_column(
        Integer, primary_key=True, autoincrement=True, comment="LD主键"
    )
    ld_name: Mapped[str] = mapped_column(
        String(255), nullable=False, comment="LD名称（对应资产类型名称）"
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
    """数据对象模板 — 含数据类型、单位、约束表达式、显示名称."""

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
    data_type: Mapped[str] = mapped_column(
        String(64), nullable=False, comment="数据类型（INT32/FLOAT32/BOOL/STRING等）"
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
    do.cdc,
    do.fc,
    do.data_type,
    do.unit,
    do.constraint_expr,
    do.display_name,

    ln.ln_id,
    ln.ln_name,
    ln.description        AS ln_description,

    ld.ld_id,
    ld.ld_name,

    ied.ied_id,
    ied.ied_name,
    ied.protocol_type,

    ied.ied_name || '/' || ld.ld_name || '/' || ln.ln_name
        || '/' || do.do_name AS full_path

FROM scada_do  do
JOIN scada_ln  ln  ON ln.ln_id = do.ln_id
JOIN scada_ld  ld  ON ld.ld_id = ln.ld_id
JOIN scada_ied ied ON ied.ied_id = ld.ied_id
"""


class MeasurementPointView(Base):
    """测点扁平视图 — IED → LD → LN → DO 四层全路径展开."""

    __tablename__ = "v_measurement_point"
    __table_args__ = {"comment": "测点扁平视图"}

    do_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    do_name: Mapped[str] = mapped_column(String(255))
    cdc: Mapped[Optional[str]] = mapped_column(String(64))
    fc: Mapped[Optional[str]] = mapped_column(String(64))
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

    full_path: Mapped[str] = mapped_column(String(1024))


Base.metadata.remove(MeasurementPointView.__table__)
