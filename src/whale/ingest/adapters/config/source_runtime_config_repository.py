"""Database-backed runtime-configuration repository for ingest."""

from __future__ import annotations

from collections.abc import Callable
from contextlib import AbstractContextManager

from sqlalchemy import select
from sqlalchemy.orm import Session

from whale.ingest.framework.persistence.orm.source_runtime_config_orm import (
    SourceRuntimeConfigORM,
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
            configs = list(
                session.scalars(
                    select(SourceRuntimeConfigORM)
                    .where(SourceRuntimeConfigORM.enabled.is_(True))
                    .order_by(SourceRuntimeConfigORM.id)
                )
            )

        return [self._to_data(config) for config in configs]

    def get_by_id(self, runtime_config_id: int) -> SourceRuntimeConfigData:
        """Return one runtime configuration or raise when it is missing."""
        with self._session_factory() as session:
            config = session.get(SourceRuntimeConfigORM, runtime_config_id)

        if config is None:
            raise LookupError(f"Runtime config `{runtime_config_id}` was not found.")

        return self._to_data(config)

    @staticmethod
    def _to_data(config: SourceRuntimeConfigORM) -> SourceRuntimeConfigData:
        """Map one ORM row into application-facing runtime data."""
        return SourceRuntimeConfigData(
            runtime_config_id=int(config.id),
            source_id=config.source_id,
            protocol=config.protocol,
            acquisition_mode=config.acquisition_mode,
            interval_ms=config.interval_ms,
            enabled=config.enabled,
        )
