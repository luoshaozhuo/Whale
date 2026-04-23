"""Database-backed OPC UA acquisition-definition repository for ingest."""

from __future__ import annotations

from collections.abc import Callable
from contextlib import AbstractContextManager

from sqlalchemy import select
from sqlalchemy.orm import Session

from whale.ingest.framework.persistence.orm.opcua_connection_orm import (
    OpcUaClientConnectionORM,
)
from whale.ingest.framework.persistence.orm.opcua_source_item_binding_orm import (
    OpcUaSourceItemBindingORM,
)
from whale.ingest.framework.persistence.orm.source_runtime_config_orm import (
    SourceRuntimeConfigORM,
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


class OpcUaSourceAcquisitionDefinitionRepository(SourceAcquisitionDefinitionPort):
    """Build one OPC UA read-once definition from explicit source bindings.

    This repository now treats `opcua_source_item_binding` as the source of
    truth for "which items does this source actually collect". The OPC UA
    NodeSet tables remain metadata catalogs and are no longer used to guess the
    binding set.
    """

    def __init__(
        self,
        session_factory: Callable[[], AbstractContextManager[Session]] = session_scope,
    ) -> None:
        """Store the session factory used for database access."""
        self._session_factory = session_factory

    def get_read_once_definition(
        self,
        runtime_config_id: int,
    ) -> SourceAcquisitionDefinition:
        """Return one OPC UA read-once definition or raise when it is missing.

        Args:
            runtime_config_id: Primary key of `source_runtime_config`.

        Raises:
            LookupError: Runtime config, connection config, or enabled bindings
                are missing.
        """
        with self._session_factory() as session:
            runtime_config = session.get(SourceRuntimeConfigORM, runtime_config_id)
            if runtime_config is None:
                raise LookupError(f"Runtime config `{runtime_config_id}` was not found.")

            connection = session.scalar(
                select(OpcUaClientConnectionORM).where(
                    OpcUaClientConnectionORM.name == runtime_config.source_id,
                )
            )
            if connection is None:
                raise LookupError(
                    f"Connection config for source `{runtime_config.source_id}` was not found."
                )

            bindings = list(
                session.scalars(
                    select(OpcUaSourceItemBindingORM)
                    .where(
                        OpcUaSourceItemBindingORM.source_id == runtime_config.source_id,
                        OpcUaSourceItemBindingORM.enabled.is_(True),
                    )
                    .order_by(
                        OpcUaSourceItemBindingORM.sort_order,
                        OpcUaSourceItemBindingORM.id,
                    )
                )
            )

        if not bindings:
            raise LookupError(
                f"No enabled item bindings were found for source `{runtime_config.source_id}`."
            )

        return SourceAcquisitionDefinition(
            runtime_config_id=int(runtime_config.id),
            source_id=runtime_config.source_id,
            source_name=connection.name,
            protocol=runtime_config.protocol,
            connection=SourceConnectionData(
                endpoint=connection.endpoint,
                security_policy=connection.security_policy,
                security_mode=connection.security_mode,
                update_interval_ms=connection.update_interval_ms,
            ),
            items=[
                AcquisitionItemData(
                    key=binding.item_key,
                    address=binding.node_address,
                    namespace_uri=binding.namespace_uri,
                    display_name=binding.display_name,
                )
                for binding in bindings
            ],
        )
