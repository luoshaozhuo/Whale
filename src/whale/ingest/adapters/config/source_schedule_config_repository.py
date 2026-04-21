"""Database-backed source schedule configuration repository for ingest."""

from __future__ import annotations

from sqlalchemy import select

from whale.ingest.framework.persistence.orm.source_runtime_config_orm import (
    SourceRuntimeConfigORM,
)
from whale.ingest.framework.persistence.session import session_scope
from whale.ingest.ports.source.source_runtime_config_port import (
    SourceRuntimeConfigPort,
)
from whale.ingest.usecases.dtos.source_runtime_config_data import (
    SourceRuntimeConfigData,
)


class SourceScheduleConfigRepository(SourceRuntimeConfigPort):
    """Load enabled source schedule configuration from the ingest database."""

    def get_enabled_sources(self) -> list[SourceRuntimeConfigData]:
        """Return enabled source runtime configurations."""
        with session_scope() as session:
            configs = list(
                session.scalars(
                    select(SourceRuntimeConfigORM)
                    .where(SourceRuntimeConfigORM.enabled.is_(True))
                    .order_by(SourceRuntimeConfigORM.source_id)
                )
            )

        return [
            SourceRuntimeConfigData(
                source_id=config.source_id,
                protocol=config.protocol,
                acquisition_mode=config.acquisition_mode,
                interval_ms=config.interval_ms,
                enabled=config.enabled,
            )
            for config in configs
        ]
