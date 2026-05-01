"""采集任务、DO 状态缓存与发件箱模块."""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from whale.shared.persistence import Base


class AcquisitionTask(Base):
    __tablename__ = "acq_task"
    __table_args__ = (
        CheckConstraint(
            "acquisition_mode IN ('ONCE', 'POLLING', 'SUBSCRIPTION')",
            name="ck_acq_task_acquisition_mode",
        ),
        {"comment": "采集任务配置"},
    )

    task_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True, comment="任务主键")
    task_name: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, comment="任务名称")
    asset_instance_id: Mapped[int] = mapped_column(
        ForeignKey("asset_instance.asset_instance_id"), nullable=False, index=True, comment="目标资产实例"
    )
    asset_type_id: Mapped[int] = mapped_column(
        ForeignKey("asset_type.asset_type_id"), nullable=False, index=True, comment="资产类型"
    )
    ied_id: Mapped[int] = mapped_column(
        ForeignKey("scada_ied.ied_id"), nullable=False, index=True, comment="采集测点模板（IED）"
    )
    protocol_type: Mapped[str] = mapped_column(String(64), nullable=False, comment="协议类型")
    endpoint: Mapped[str] = mapped_column(String(512), nullable=False, comment="协议连接端点")
    namespace_uri: Mapped[Optional[str]] = mapped_column(String(512), nullable=True, comment="OPC UA 命名空间")
    sampling_interval_ms: Mapped[int] = mapped_column(Integer, nullable=False, comment="采集周期（毫秒）")
    acquisition_mode: Mapped[str] = mapped_column(String(32), nullable=False, comment="采集模式")
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=0, comment="优先级")
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, comment="是否启用")
    params: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict, comment="协议保留参数")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())

    asset_instance: Mapped["AssetInstance"] = relationship(back_populates="acquisition_tasks")
    do_states: Mapped[list["DOState"]] = relationship(back_populates="task")
    outbox_messages: Mapped[list["StateSnapshotOutbox"]] = relationship(back_populates="task")


class DOState(Base):
    """DO 测点最新状态缓存 — 记录每个 (资产实例, DO模板) 的最新采集值."""

    __tablename__ = "acq_do_state"
    __table_args__ = (
        UniqueConstraint("asset_instance_id", "do_id", name="uq_acq_do_state"),
        {"comment": "DO 测点最新状态缓存"},
    )

    do_state_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True, comment="状态主键")
    task_id: Mapped[int] = mapped_column(ForeignKey("acq_task.task_id"), nullable=False, index=True, comment="所属采集任务")
    asset_instance_id: Mapped[int] = mapped_column(
        ForeignKey("asset_instance.asset_instance_id"), nullable=False, index=True, comment="所属资产实例"
    )
    do_id: Mapped[int] = mapped_column(
        ForeignKey("scada_do.do_id"), nullable=False, index=True, comment="关联 DO 模板"
    )
    value: Mapped[str] = mapped_column(Text, nullable=False, comment="最新值（序列化）")
    source_observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, comment="数据源时间戳")
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), comment="接收时间戳")
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now(), comment="本地更新时间戳")

    task: Mapped["AcquisitionTask"] = relationship(back_populates="do_states")
    do: Mapped["DO"] = relationship(back_populates="do_states")


class StateSnapshotOutbox(Base):
    """状态快照发件箱."""

    __tablename__ = "acq_outbox"
    __table_args__ = {"comment": "状态快照发件箱"}

    outbox_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True, comment="发件箱主键")
    task_id: Mapped[int] = mapped_column(ForeignKey("acq_task.task_id"), nullable=False, index=True, comment="所属采集任务")
    asset_instance_id: Mapped[int] = mapped_column(
        ForeignKey("asset_instance.asset_instance_id"), nullable=False, index=True, comment="所属资产实例"
    )
    message_id: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True, comment="消息唯一标识")
    snapshot_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True, comment="快照标识")
    schema_version: Mapped[str] = mapped_column(String(32), nullable=False, comment="schema 版本")
    message_type: Mapped[str] = mapped_column(String(64), nullable=False, comment="消息类型")
    payload: Mapped[str] = mapped_column(Text, nullable=False, comment="序列化 JSON 消息体")
    snapshot_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, comment="快照时间戳")
    published_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), comment="发件时间戳")

    task: Mapped["AcquisitionTask"] = relationship(back_populates="outbox_messages")
