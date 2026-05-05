"""Database-backed OPC UA acquisition-definition repository."""

from __future__ import annotations

from collections.abc import Callable
from contextlib import AbstractContextManager

from sqlalchemy import select
from sqlalchemy.orm import Session

from whale.ingest.framework.persistence.session import session_scope
from whale.ingest.ports.source.source_acquisition_definition_port import (
    SourceAcquisitionDefinitionPort,
)
from whale.ingest.usecases.dtos.acquisition_item_data import AcquisitionItemData
from whale.ingest.usecases.dtos.source_acquisition_definition import (
    SourceAcquisitionDefinition,
)
from whale.ingest.usecases.dtos.source_connection_data import SourceConnectionData
from whale.ingest.usecases.dtos.source_runtime_config_data import SourceRuntimeConfigData
from whale.shared.persistence.orm import (
    AcquisitionTask, CommunicationEndpoint, LDInstance, SignalProfileItem,
)


class OpcUaSourceAcquisitionDefinitionRepository(SourceAcquisitionDefinitionPort):

    def __init__(
        self,
        session_factory: Callable[[], AbstractContextManager[Session]] = session_scope,
    ) -> None:
        self._session_factory = session_factory

    def get_config(
        self,
        runtime_config: SourceRuntimeConfigData,
    ) -> SourceAcquisitionDefinition:
        with self._session_factory() as session:
            task = session.get(AcquisitionTask, runtime_config.runtime_config_id)
            if task is None:
                raise LookupError(
                    f"AcquisitionTask `{runtime_config.runtime_config_id}` not found."
                )

            ld = session.get(LDInstance, task.ld_instance_id)
            if ld is None:
                raise LookupError(f"LDInstance `{task.ld_instance_id}` not found.")

            ep = session.get(CommunicationEndpoint, ld.endpoint_id)
            if ep is None:
                raise LookupError(f"CommunicationEndpoint `{ld.endpoint_id}` not found.")

            if ld.signal_profile_id is None:
                raise LookupError(f"LDInstance `{ld.ld_instance_id}` has no signal_profile_id.")

            items = session.scalars(
                select(SignalProfileItem)
                .where(SignalProfileItem.signal_profile_id == ld.signal_profile_id)
                .order_by(SignalProfileItem.profile_item_id)
            ).all()

            scheme = "opc.https" if ep.transport == "HTTPS" else "opc.tcp"
            ep_url = f"{scheme}://{ep.host}:{ep.port}" if ep.host and ep.port else ""

        return SourceAcquisitionDefinition(
            ld_id=ld.ld_name,
            connection=SourceConnectionData(
                endpoint=ep_url,
                params={"namespace_uri": ep.namespace_uri or ""},
            ),
            items=[
                AcquisitionItemData(
                    key=item.do_name,
                    locator=f"{ld.path_prefix}/{item.relative_path}",
                )
                for item in items
            ],
            request_timeout_ms=task.request_timeout_ms,
            poll_interval_ms=task.poll_interval_ms,
        )
