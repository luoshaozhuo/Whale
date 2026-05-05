"""Database-backed runtime-configuration repository for ingest."""

from __future__ import annotations

from collections.abc import Callable
from contextlib import AbstractContextManager

from sqlalchemy import select
from sqlalchemy.orm import Session

from whale.ingest.framework.persistence.session import session_scope
from whale.ingest.ports.runtime.source_runtime_config_port import (
    SourceRuntimeConfigPort,
)
from whale.ingest.usecases.dtos.source_runtime_config_data import (
    SourceRuntimeConfigData,
)
from whale.shared.persistence.orm import AcquisitionTask, AssetInstance, LDInstance


class SourceRuntimeConfigRepository(SourceRuntimeConfigPort):
    """Load runtime config rows from the ingest database."""

    def __init__(
        self,
        session_factory: Callable[[], AbstractContextManager[Session]] = session_scope,
    ) -> None:
        self._session_factory = session_factory

    def list_enabled(self) -> list[SourceRuntimeConfigData]:
        """Return enabled runtime configurations ordered by task id."""
        with self._session_factory() as session:
            tasks = list(
                session.scalars(
                    select(AcquisitionTask)
                    .where(AcquisitionTask.enabled.is_(True))
                    .order_by(AcquisitionTask.task_id)
                )
            )
            return [self._to_data(session, task) for task in tasks]

    @staticmethod
    def _to_data(session: Session, task: AcquisitionTask) -> SourceRuntimeConfigData:
        ld = session.get(LDInstance, task.ld_instance_id)
        if ld is None:
            raise LookupError(
                f"LDInstance `{task.ld_instance_id}` was not found for task `{task.task_id}`."
            )
        asset = session.get(AssetInstance, ld.asset_instance_id)
        if asset is None:
            raise LookupError(
                f"AssetInstance `{ld.asset_instance_id}` was not found for task `{task.task_id}`."
            )
        return SourceRuntimeConfigData(
            runtime_config_id=task.task_id,
            source_id=asset.asset_code,
            protocol="opcua",
            acquisition_mode=task.acquisition_mode,
            interval_ms=0,  # interval is now per-signal in profile items
            enabled=task.enabled,
        )
