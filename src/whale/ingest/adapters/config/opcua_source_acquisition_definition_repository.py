"""Database-backed OPC UA acquisition-definition repository for ingest."""

from __future__ import annotations

from collections.abc import Callable
from contextlib import AbstractContextManager

from sqlalchemy import select
from sqlalchemy.orm import Session

from whale.ingest.framework.persistence.orm.acquisition_model_orm import (
    AcquisitionModelORM,
)
from whale.ingest.framework.persistence.orm.acquisition_task_orm import (
    AcquisitionTaskORM,
)
from whale.ingest.framework.persistence.orm.acquisition_variable_orm import (
    AcquisitionVariableORM,
)
from whale.ingest.framework.persistence.orm.device_orm import (
    DeviceORM,
)
from whale.ingest.framework.persistence.session import session_scope
from whale.ingest.ports.source.source_acquisition_definition_port import (
    SourceAcquisitionDefinitionPort,
)
from whale.ingest.usecases.dtos.acquisition_item_data import AcquisitionItemData
from whale.ingest.usecases.dtos.source_acquisition_definition import (
    SourceAcquisitionDefinition,
)
from whale.ingest.usecases.dtos.source_connection_data import SourceConnectionData
from whale.ingest.usecases.dtos.source_runtime_config_data import (
    SourceRuntimeConfigData,
)


class OpcUaSourceAcquisitionDefinitionRepository(SourceAcquisitionDefinitionPort):
    """Load OPC UA acquisition config from tasks, devices and acquisition models."""

    def __init__(
        self,
        session_factory: Callable[[], AbstractContextManager[Session]] = session_scope,
    ) -> None:
        """Store the session factory used for database access."""
        self._session_factory = session_factory

    def get_config(
        self,
        runtime_config: SourceRuntimeConfigData,
    ) -> SourceAcquisitionDefinition:
        """Load one OPC UA runtime config into acquisition config data.

        Args:
            runtime_config: Runtime-config snapshot for the current refresh step.

        Raises:
            LookupError: Task, device, model or acquisition-variable rows are missing.
        """
        with self._session_factory() as session:
            task = session.get(AcquisitionTaskORM, runtime_config.runtime_config_id)
            if task is None:
                raise LookupError(
                    f"Acquisition task `{runtime_config.runtime_config_id}` was not found."
                )

            device = session.get(DeviceORM, task.device_id)
            if device is None:
                raise LookupError(f"Device `{task.device_id}` was not found for task `{task.id}`.")

            model = session.scalar(
                select(AcquisitionModelORM).where(
                    AcquisitionModelORM.model_id == task.model_id,
                    AcquisitionModelORM.model_version == task.model_version,
                )
            )
            if model is None:
                raise LookupError(
                    "No acquisition model was found for "
                    f"model `{task.model_id}` version `{task.model_version}`."
                )

            variable_rows = list(
                session.scalars(
                    select(AcquisitionVariableORM)
                    .where(AcquisitionVariableORM.model_id == model.id)
                    .order_by(AcquisitionVariableORM.id)
                )
            )

        if not variable_rows:
            raise LookupError(
                "No acquisition variables were found for "
                f"model `{task.model_id}` version `{task.model_version}`."
            )

        return SourceAcquisitionDefinition(
            model_id=task.model_id,
            connection=SourceConnectionData(
                host=task.host,
                port=task.port,
                username=task.username,
                password=task.password,
                params=dict(task.connection_params),
            ),
            items=[
                AcquisitionItemData(
                    key=variable_row.variable_key,
                    locator=variable_row.locator.format(
                        device_code=device.device_code,
                        source_id=device.device_code,
                        key=variable_row.variable_key,
                    ),
                    locator_type=variable_row.locator_type,
                    display_name=variable_row.display_name,
                    params=dict(variable_row.variable_params),
                )
                for variable_row in variable_rows
            ],
        )
