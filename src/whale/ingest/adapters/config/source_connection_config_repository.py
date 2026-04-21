"""Database-backed source connection configuration repository for ingest."""

from __future__ import annotations

from sqlalchemy import select

from whale.ingest.framework.persistence.orm.opcua_connection_orm import (
    OpcUaClientConnectionORM,
)
from whale.ingest.framework.persistence.session import session_scope
from whale.ingest.ports.source.source_config_port import SourceConfigPort
from whale.ingest.usecases.dtos.source_config_data import SourceConfigData


class SourceConnectionConfigRepository(SourceConfigPort):
    """Load source connection configuration from the ingest background database."""

    def get_source_config(self, source_id: str) -> SourceConfigData | None:
        """Return source configuration for one source identifier."""
        with session_scope() as session:
            config = session.scalar(
                select(OpcUaClientConnectionORM).where(
                    OpcUaClientConnectionORM.name == source_id,
                )
            )
            if config is None and source_id.isdigit():
                config = session.get(OpcUaClientConnectionORM, int(source_id))

        if config is None:
            return None

        return SourceConfigData(
            source_id=source_id,
            source_name=config.name,
            protocol="opcua",
            endpoint=config.endpoint,
            security_policy=config.security_policy,
            security_mode=config.security_mode,
            update_interval_ms=config.update_interval_ms,
            enabled=config.enabled,
        )
