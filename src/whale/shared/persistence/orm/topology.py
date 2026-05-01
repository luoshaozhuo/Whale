"""场站电气拓扑与网络拓扑模块."""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from whale.shared.persistence import Base


class ElectricalTopology(Base):
    """电气拓扑 — 描述场站设备间电气连接关系."""

    __tablename__ = "topo_electrical"
    __table_args__ = {"comment": "电气拓扑连接"}

    topo_id: Mapped[int] = mapped_column(
        Integer, primary_key=True, autoincrement=True, comment="拓扑主键"
    )
    topo_name: Mapped[str] = mapped_column(String(255), nullable=False, comment="连接名称")
    source_asset_instance_id: Mapped[int] = mapped_column(
        ForeignKey("asset_instance.asset_instance_id"), nullable=False, index=True,
        comment="源资产实例"
    )
    target_asset_instance_id: Mapped[int] = mapped_column(
        ForeignKey("asset_instance.asset_instance_id"), nullable=False, index=True,
        comment="目标资产实例"
    )
    voltage_level_kv: Mapped[Optional[float]] = mapped_column(
        Float, nullable=True, comment="电压等级（kV）"
    )
    cable_type: Mapped[Optional[str]] = mapped_column(
        String(128), nullable=True, comment="电缆型号"
    )
    cable_length_m: Mapped[Optional[float]] = mapped_column(
        Float, nullable=True, comment="电缆长度（m）"
    )
    max_current_a: Mapped[Optional[float]] = mapped_column(
        Float, nullable=True, comment="最大载流量（A）"
    )
    topology_type: Mapped[str] = mapped_column(
        String(64), nullable=False, default="radial",
        comment="拓扑类型（radial/ring/mesh/busbar）"
    )
    description: Mapped[Optional[str]] = mapped_column(
        String(512), nullable=True, comment="连接说明"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    source_asset: Mapped["AssetInstance"] = relationship(
        back_populates="topology_sources", foreign_keys=[source_asset_instance_id]
    )
    target_asset: Mapped["AssetInstance"] = relationship(
        back_populates="topology_targets", foreign_keys=[target_asset_instance_id]
    )


class NetworkTopology(Base):
    """网络拓扑 — 描述场站设备间通信网络连接关系."""

    __tablename__ = "topo_network"
    __table_args__ = {"comment": "网络拓扑连接"}

    topo_id: Mapped[int] = mapped_column(
        Integer, primary_key=True, autoincrement=True, comment="拓扑主键"
    )
    topo_name: Mapped[str] = mapped_column(String(255), nullable=False, comment="连接名称")
    source_asset_instance_id: Mapped[int] = mapped_column(
        ForeignKey("asset_instance.asset_instance_id"), nullable=False, index=True,
        comment="源设备资产实例"
    )
    target_device: Mapped[str] = mapped_column(
        String(255), nullable=False, comment="目标网络设备（交换机/路由器/防火墙）"
    )
    source_ip: Mapped[Optional[str]] = mapped_column(
        String(45), nullable=True, comment="源设备IP地址"
    )
    target_ip: Mapped[Optional[str]] = mapped_column(
        String(45), nullable=True, comment="目标设备IP地址"
    )
    subnet_mask: Mapped[Optional[str]] = mapped_column(
        String(45), nullable=True, comment="子网掩码"
    )
    gateway: Mapped[Optional[str]] = mapped_column(
        String(45), nullable=True, comment="网关地址"
    )
    protocol: Mapped[Optional[str]] = mapped_column(
        String(64), nullable=True, comment="通信协议（OPC UA/Modbus TCP/EtherNet/IP/PROFINET）"
    )
    port: Mapped[Optional[int]] = mapped_column(
        Integer, nullable=True, comment="端口号"
    )
    vlan_id: Mapped[Optional[int]] = mapped_column(
        Integer, nullable=True, comment="VLAN ID"
    )
    fiber_type: Mapped[Optional[str]] = mapped_column(
        String(64), nullable=True, comment="光纤类型（单模/多模）"
    )
    redundancy_protocol: Mapped[Optional[str]] = mapped_column(
        String(64), nullable=True, comment="冗余协议（RSTP/MRP/HSR/PRP等）"
    )
    description: Mapped[Optional[str]] = mapped_column(
        String(512), nullable=True, comment="连接说明"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    source_asset: Mapped["AssetInstance"] = relationship(foreign_keys=[source_asset_instance_id])
