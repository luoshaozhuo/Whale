"""SourceAcquisitionUseCase — 统一启动 source 采集。"""

from __future__ import annotations

from whale.ingest.usecases.dtos.source_acquisition_request import (
    SourceAcquisitionRequest,
)
from whale.ingest.usecases.dtos.source_acquisition_start_result import (
    SourceAcquisitionStartResult,
)
from whale.ingest.usecases.roles.polling_acquisition_role import (
    PollingAcquisitionRole,
)
from whale.ingest.usecases.roles.subscription_acquisition_role import (
    SubscriptionAcquisitionRole,
)


class SourceAcquisitionUseCase:
    """统一 source 采集入口。

    职责：
    - 校验 SourceAcquisitionRequest；
    - 根据 acquisition_mode 分发到对应 role；
    - 不直接 read；
    - 不直接 subscribe；
    - 不直接写 cache。
    """

    _POLLING_MODES = {"READ", "READ_ONCE", "ONCE", "POLLING"}
    _SUBSCRIPTION_MODES = {"SUBSCRIBE", "SUBSCRIPTION"}
    _SUPPORTED_MODES = _POLLING_MODES | _SUBSCRIPTION_MODES

    def __init__(
        self,
        *,
        polling_role: PollingAcquisitionRole,
        subscription_role: SubscriptionAcquisitionRole,
    ) -> None:
        self._polling_role = polling_role
        self._subscription_role = subscription_role

    async def start(
        self,
        request: SourceAcquisitionRequest,
    ) -> SourceAcquisitionStartResult:
        """校验并启动采集。"""

        mode = request.execution.acquisition_mode.upper()
        self._validate_request(request=request, mode=mode)

        if mode in self._POLLING_MODES:
            return self._polling_role.start(request)

        if mode in self._SUBSCRIPTION_MODES:
            return await self._subscription_role.start(request)

        raise ValueError(
            f"Unsupported acquisition_mode: {request.execution.acquisition_mode}"
        )

    def _validate_request(
        self,
        *,
        request: SourceAcquisitionRequest,
        mode: str,
    ) -> None:
        """校验 source 采集请求。"""

        if mode not in self._SUPPORTED_MODES:
            raise ValueError(
                f"Unsupported acquisition_mode: {request.execution.acquisition_mode}"
            )

        if not request.request_id:
            raise ValueError("request_id is required")

        if request.task_id <= 0:
            raise ValueError("task_id must be greater than 0")

        if not request.connections:
            raise ValueError("SourceAcquisitionRequest.connections cannot be empty")

        if not request.items:
            raise ValueError("SourceAcquisitionRequest.items cannot be empty")

        for connection in request.connections:
            if not connection.ld_name:
                raise ValueError("ld_name is required")

        if mode in self._POLLING_MODES:
            self._validate_polling_request(request)

        if mode in self._SUBSCRIPTION_MODES:
            self._validate_subscription_request(request)

    @staticmethod
    def _validate_polling_request(request: SourceAcquisitionRequest) -> None:
        """校验主动采集请求。"""

        execution = request.execution

        if execution.interval_ms <= 0:
            raise ValueError("Polling interval_ms must be greater than 0")

        if execution.max_iteration is not None and execution.max_iteration <= 0:
            raise ValueError("Polling max_iteration must be greater than 0")

        if execution.polling_max_concurrent_connections <= 0:
            raise ValueError(
                "polling_max_concurrent_connections must be greater than 0"
            )

        if execution.polling_connection_start_interval_ms < 0:
            raise ValueError(
                "polling_connection_start_interval_ms cannot be negative"
            )

    @staticmethod
    def _validate_subscription_request(request: SourceAcquisitionRequest) -> None:
        """校验订阅采集请求。"""

        execution = request.execution

        if execution.subscription_start_interval_ms < 0:
            raise ValueError("subscription_start_interval_ms cannot be negative")

        if execution.subscription_notification_queue_size <= 0:
            raise ValueError(
                "subscription_notification_queue_size must be greater than 0"
            )

        if execution.subscription_notification_worker_count <= 0:
            raise ValueError(
                "subscription_notification_worker_count must be greater than 0"
            )

        if execution.subscription_notification_max_lag_ms <= 0:
            raise ValueError(
                "subscription_notification_max_lag_ms must be greater than 0"
            )