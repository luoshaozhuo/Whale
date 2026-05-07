"""采集诊断模块 — ingest_source_health 与 ingest_runtime_event."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    JSON,
    String,
    Text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from whale.shared.persistence import Base


class IngestSourceHealthOrm(Base):
    """采集任务 / source 的当前健康状态."""

    __tablename__ = "ingest_source_health"
    __table_args__ = (
        Index("ix_source_health_status", "health_status"),
        Index("ix_source_health_alive_at", "last_alive_at"),
        Index("ix_source_health_failure_at", "last_failure_at"),
        Index("ix_source_health_ld_instance", "ld_instance_id"),
        {"comment": "采集源健康状态"},
    )

    health_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True, comment="健康记录主键")

    task_id: Mapped[int] = mapped_column(
        ForeignKey("acq_task.task_id"), unique=True, nullable=False, index=True,
        comment="采集任务 ID，每个 acq_task 对应一条 health"
    )
    ld_instance_id: Mapped[int] = mapped_column(
        ForeignKey("scada_ld_instance.ld_instance_id"), nullable=False, index=True,
        comment="LD 实例 ID，冗余保存便于按设备查询"
    )
    acquisition_mode: Mapped[str] = mapped_column(
        String(32), nullable=False, comment="采集模式：READ_ONCE / POLLING / SUBSCRIBE"
    )
    health_status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="UNKNOWN",
        comment="健康状态：UNKNOWN / HEALTHY / DEGRADED / OFFLINE"
    )
    last_success_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, comment="最近一次采集成功时间"
    )
    last_failure_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, comment="最近一次失败时间"
    )
    last_alive_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
        comment="最近一次确认采集链路仍然活着的时间；subscribe 模式使用 datachange/keep-alive/watchdog 更新"
    )
    last_datachange_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
        comment="subscribe 模式最近一次 datachange 时间；值长期不变时该字段可能不更新，不应单独用于判断失活"
    )
    consecutive_failure_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, comment="连续失败次数，成功后清零"
    )
    total_failure_count: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=0, comment="累计失败次数"
    )
    last_failure_category: Mapped[str | None] = mapped_column(
        String(64), nullable=True,
        comment="最近一次失败类别：SOURCE_UNAVAILABLE / SOURCE_TIMEOUT / DATA_INVALID 等"
    )
    last_error_code: Mapped[str | None] = mapped_column(
        String(128), nullable=True, comment="最近一次错误码"
    )
    last_error_message: Mapped[str | None] = mapped_column(
        Text, nullable=True, comment="最近一次错误信息"
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now(),
        comment="更新时间"
    )


class IngestRuntimeEventOrm(Base):
    """历史故障、降级、恢复、发布异常等结构化事件."""

    __tablename__ = "ingest_runtime_event"
    __table_args__ = (
        Index("ix_runtime_event_task_time", "task_id", "occurred_at"),
        Index("ix_runtime_event_type_time", "event_type", "occurred_at"),
        Index("ix_runtime_event_stage_time", "stage", "occurred_at"),
        Index("ix_runtime_event_severity_time", "severity", "occurred_at"),
        Index("ix_runtime_event_ld_time", "ld_instance_id", "occurred_at"),
        Index("ix_runtime_event_category_time", "failure_category", "occurred_at"),
        {"comment": "采集运行时事件"},
    )

    event_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True, comment="事件主键")

    event_type: Mapped[str] = mapped_column(
        String(64), nullable=False,
        comment="事件类型：CONFIG_INVALID / ACQUISITION_FAILED / CACHE_UPDATE_FAILED / SNAPSHOT_INVALID / PUBLISH_FAILED / RECOVERED 等"
    )
    failure_category: Mapped[str | None] = mapped_column(
        String(64), nullable=True, comment="失败类别"
    )
    severity: Mapped[str] = mapped_column(
        String(32), nullable=False, default="ERROR",
        comment="严重级别：INFO / WARNING / ERROR / CRITICAL"
    )
    task_id: Mapped[int | None] = mapped_column(
        ForeignKey("acq_task.task_id"), nullable=True, index=True, comment="关联采集任务"
    )
    ld_instance_id: Mapped[int | None] = mapped_column(
        Integer, nullable=True, comment="LD 实例 ID，冗余保存便于按设备查故障"
    )
    acquisition_mode: Mapped[str | None] = mapped_column(
        String(32), nullable=True, comment="采集模式"
    )
    stage: Mapped[str] = mapped_column(
        String(64), nullable=False,
        comment="发生阶段：VALIDATION / PLAN_BUILD / SCHEDULER / ACQUISITION / CACHE_UPDATE / SUBSCRIBE / SNAPSHOT_READ / SNAPSHOT_VALIDATE / SNAPSHOT_ASSEMBLE / PUBLISH"
    )
    protocol: Mapped[str | None] = mapped_column(
        String(32), nullable=True, comment="协议：OPCUA / MODBUS / IEC61850"
    )
    error_code: Mapped[str | None] = mapped_column(
        String(128), nullable=True, comment="错误码"
    )
    error_message: Mapped[str | None] = mapped_column(
        Text, nullable=True, comment="错误信息"
    )
    exception_type: Mapped[str | None] = mapped_column(
        String(255), nullable=True, comment="异常类型"
    )
    traceback_hash: Mapped[str | None] = mapped_column(
        String(128), nullable=True, comment="traceback 哈希，便于归并，完整 traceback 仍交日志系统"
    )
    retryable: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, comment="是否可重试"
    )
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), comment="发生时间"
    )
    resolved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, comment="解决时间，RECOVERED 事件必须填写"
    )
    attributes_json: Mapped[dict] = mapped_column(
        JSON, nullable=False, default=dict, comment="扩展信息"
    )
