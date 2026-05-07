"""AcquisitionFailureClassifierRole — 异常 → failure_category + error_code."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass

from whale.ingest.usecases.dtos.diagnostics_constants import ErrorCode, FailureCategory


@dataclass(slots=True)
class FailureClassification:
    """结构化失败分类结果."""

    category: str
    code: str


class AcquisitionFailureClassifierRole:
    """把异常转换成 failure_category + error_code，不访问数据库/网络."""

    def classify(
        self,
        exception: Exception,
        protocol: str | None = None,
    ) -> FailureClassification:
        category, code = self._classify_impl(exception, protocol)
        return FailureClassification(category=category, code=code)

    @staticmethod
    def _classify_impl(
        exception: Exception,
        protocol: str | None,
    ) -> tuple[str, str]:
        exc_type = type(exception)
        exc_msg = str(exception).lower()

        if isinstance(exception, asyncio.TimeoutError):
            return FailureCategory.SOURCE_TIMEOUT, ErrorCode.OPCUA_READ_TIMEOUT

        if isinstance(exception, ConnectionError):
            return FailureCategory.SOURCE_UNAVAILABLE, ErrorCode.OPCUA_CONNECTION_FAILED

        if isinstance(exception, OSError):
            if "connection" in exc_msg or "connect" in exc_msg:
                return FailureCategory.SOURCE_UNAVAILABLE, ErrorCode.OPCUA_CONNECTION_FAILED
            if "timeout" in exc_msg:
                return FailureCategory.SOURCE_TIMEOUT, ErrorCode.OPCUA_READ_TIMEOUT
            return FailureCategory.SOURCE_UNAVAILABLE, ErrorCode.OPCUA_CONNECTION_FAILED

        if isinstance(exception, ValueError):
            return FailureCategory.DATA_INVALID, ErrorCode.OPCUA_BAD_STATUS_CODE

        if "redis" in exc_msg or "REDIS" in str(exception).upper():
            if "connection" in exc_msg:
                return FailureCategory.CACHE_UPDATE_FAILED, ErrorCode.REDIS_CONNECTION_ERROR
            if "timeout" in exc_msg:
                return FailureCategory.CACHE_UPDATE_FAILED, ErrorCode.REDIS_WRITE_TIMEOUT
            return FailureCategory.CACHE_UPDATE_FAILED, ErrorCode.REDIS_CONNECTION_ERROR

        if "kafka" in exc_msg:
            if "timeout" in exc_msg or "ack" in exc_msg:
                return FailureCategory.PUBLISH_FAILED, ErrorCode.KAFKA_ACK_TIMEOUT
            return FailureCategory.PUBLISH_FAILED, ErrorCode.KAFKA_BROKER_UNAVAILABLE

        return FailureCategory.UNKNOWN_ERROR, exc_type.__name__.upper()
