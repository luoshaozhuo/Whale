"""RuntimePlanBuildUseCase — 读取 DB 配置，校验，生成可执行的 SourceAcquisitionExecutionPlan."""

from __future__ import annotations

import uuid

from whale.ingest.ports.source.source_acquisition_definition_port import (
    SourceAcquisitionDefinitionPort,
)
from whale.ingest.ports.runtime.source_runtime_config_port import (
    SourceRuntimeConfigPort,
)
from whale.ingest.usecases.dtos.source_acquisition_execution_plan import (
    SourceAcquisitionExecutionPlan,
)
from whale.ingest.usecases.dtos.source_runtime_config_data import (
    SourceRuntimeConfigData,
)
from whale.ingest.usecases.roles.runtime_config_validation_role import (
    RuntimeConfigValidationRole,
    ValidationResult,
)


class RuntimePlanBuildUseCase:
    """读取 enabled acq_task，校验配置，生成 SourceAcquisitionExecutionPlan 列表.

    配置错误 fail fast，不生成 plan。
    """

    def __init__(
        self,
        runtime_config_port: SourceRuntimeConfigPort,
        acquisition_definition_port: SourceAcquisitionDefinitionPort,
        validation_role: RuntimeConfigValidationRole | None = None,
    ) -> None:
        self._runtime_config_port = runtime_config_port
        self._acquisition_definition_port = acquisition_definition_port
        self._validation_role = validation_role or RuntimeConfigValidationRole()

    def build_plans_from_enabled(self) -> list[SourceAcquisitionExecutionPlan]:
        configs = self._runtime_config_port.list_enabled()
        return self._build_plans(configs)

    def build_plans(
        self,
        runtime_configs: list[SourceRuntimeConfigData],
    ) -> list[SourceAcquisitionExecutionPlan]:
        return self._build_plans(runtime_configs)

    def _build_plans(
        self,
        configs: list[SourceRuntimeConfigData],
    ) -> list[SourceAcquisitionExecutionPlan]:
        plans: list[SourceAcquisitionExecutionPlan] = []
        invalid_configs: list[tuple[SourceRuntimeConfigData, ValidationResult]] = []

        for config in configs:
            try:
                definition = self._acquisition_definition_port.get_config(config)
            except Exception as exc:
                invalid_configs.append(
                    (config, ValidationResult(is_valid=False, errors=[str(exc)]))
                )
                continue

            validation = self._validation_role.validate(config, definition)
            if not validation.is_valid:
                invalid_configs.append((config, validation))
                continue

            plans.append(
                SourceAcquisitionExecutionPlan(
                    plan_id=uuid.uuid4().hex,
                    task_id=config.runtime_config_id,
                    ld_instance_id=0,
                    model_id=definition.ld_id,
                    acquisition_mode=config.acquisition_mode,
                    protocol=config.protocol,
                    endpoint_config=definition.connection,
                    request_items=list(definition.items),
                    request_timeout_ms=definition.request_timeout_ms,
                    freshness_timeout_ms=30000,
                    alive_timeout_ms=60000,
                    protocol_params={},
                )
            )

        if invalid_configs:
            errors = []
            for cfg, vr in invalid_configs:
                errors.append(
                    f"config {cfg.runtime_config_id}: {'; '.join(vr.errors)}"
                )
            raise RuntimeError(
                f"Plan build failed for {len(invalid_configs)} config(s): "
                + " | ".join(errors)
            )

        return plans
