"""Database-backed runtime-configuration repository for ingest."""

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
from whale.ingest.framework.persistence.orm.device_orm import (
    DeviceORM,
)
from whale.ingest.framework.persistence.session import session_scope
from whale.ingest.ports.runtime.source_runtime_config_port import (
    SourceRuntimeConfigPort,
)
from whale.ingest.usecases.dtos.source_runtime_config_data import (
    SourceRuntimeConfigData,
)


class SourceRuntimeConfigRepository(SourceRuntimeConfigPort):
    """Load runtime config rows from the ingest database."""

    def __init__(
        self,
        session_factory: Callable[[], AbstractContextManager[Session]] = session_scope,
    ) -> None:
        """Store the session factory used for database access."""
        self._session_factory = session_factory

    def list_enabled(self) -> list[SourceRuntimeConfigData]:
        """Return enabled runtime configurations ordered by runtime-config id."""
        with self._session_factory() as session:
            tasks = list(
                session.scalars(
                    select(AcquisitionTaskORM)
                    .where(AcquisitionTaskORM.enabled.is_(True))
                    .order_by(AcquisitionTaskORM.id)
                )
            )

            return [self._to_data(session, task) for task in tasks]

    @staticmethod
    def _to_data(session: Session, task: AcquisitionTaskORM) -> SourceRuntimeConfigData:
        """Map one ORM row into application-facing runtime data."""
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
                "Protocol was not found for "
                f"model `{task.model_id}` version `{task.model_version}`."
            )

        return SourceRuntimeConfigData(
            runtime_config_id=int(task.id),
            source_id=device.device_code,
            protocol=model.protocol,
            acquisition_mode=task.acquisition_mode,
            interval_ms=task.interval_ms,
            enabled=task.enabled,
        )
