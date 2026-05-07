"""RuntimeConfigValidationRole — job 注册前 fail-fast 校验."""

from __future__ import annotations

from dataclasses import dataclass, field

from whale.ingest.usecases.dtos.source_acquisition_definition import (
    SourceAcquisitionDefinition,
)
from whale.ingest.usecases.dtos.source_runtime_config_data import (
    SourceRuntimeConfigData,
)


@dataclass(slots=True)
class ValidationResult:
    """单条 runtime config 的校验结果."""

    is_valid: bool
    errors: list[str] = field(default_factory=list)


class RuntimeConfigValidationRole:
    """启动 / 注册 job 前校验配置合法性，不在 ExecuteSourceAcquisitionUseCase 每周期重复调用."""

    def validate(
        self,
        runtime_config: SourceRuntimeConfigData,
        definition: SourceAcquisitionDefinition,
    ) -> ValidationResult:
        errors: list[str] = self._collect_errors(runtime_config, definition)
        return ValidationResult(is_valid=len(errors) == 0, errors=errors)

    def _collect_errors(
        self,
        runtime_config: SourceRuntimeConfigData,
        definition: SourceAcquisitionDefinition,
    ) -> list[str]:
        errors: list[str] = []

        if not runtime_config.enabled:
            errors.append("runtime config is disabled")

        mode = runtime_config.acquisition_mode.upper()
        if mode not in {"READ_ONCE", "POLLING", "SUBSCRIBE", "REPORT"}:
            errors.append(f"unsupported acquisition mode: {runtime_config.acquisition_mode}")

        task_interval_ms = self._task_interval_ms(runtime_config, definition)
        if task_interval_ms is not None and definition.request_timeout_ms >= task_interval_ms:
            errors.append(
                f"request_timeout_ms ({definition.request_timeout_ms}) "
                f"must be less than task_interval_ms ({task_interval_ms})"
            )

        if not definition.connection.endpoint:
            errors.append("endpoint is missing")

        if not definition.items:
            errors.append("profile items are empty")

        if definition.ld_id is None:
            errors.append("ld_id is missing")

        return errors

    @staticmethod
    def _task_interval_ms(
        runtime_config: SourceRuntimeConfigData,
        definition: SourceAcquisitionDefinition,
    ) -> int | None:
        mode = runtime_config.acquisition_mode.upper()
        if mode == "POLLING":
            return definition.poll_interval_ms or runtime_config.interval_ms
        if mode == "SUBSCRIBE":
            return definition.poll_interval_ms
        return None
