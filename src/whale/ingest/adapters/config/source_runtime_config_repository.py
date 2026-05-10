"""Database-backed runtime-configuration repository for ingest."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from contextlib import AbstractContextManager

from sqlalchemy import select
from sqlalchemy.orm import Session

from whale.ingest.framework.persistence.session import session_scope
from whale.ingest.ports.runtime.source_runtime_config_port import (
    ServerRuntimeConfigData,
    SignalProfileItemRuntimeData,
    SourceRuntimeConfigData,
    SourceRuntimeConfigPort,
)
from whale.shared.persistence.orm import (
    AcquisitionTask,
    AssetInstance,
    CommunicationEndpoint,
    LDInstance,
    ScadaDataType,
    SignalProfileItem,
    IED,
)


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

    def list_servers(
        self,
        *,
        group_by: Sequence[str] = (),
        first_group_only: bool = False,
    ) -> list[ServerRuntimeConfigData]:
        """Return server entries ordered for deterministic profile grouping."""
        with self._session_factory() as session:
            rows = session.execute(
                select(
                    CommunicationEndpoint.endpoint_id,
                    IED.ied_name,
                    AssetInstance.asset_code,
                    AssetInstance.asset_name,
                    LDInstance.ld_name,
                    CommunicationEndpoint.application_protocol,
                    CommunicationEndpoint.transport,
                    CommunicationEndpoint.host,
                    CommunicationEndpoint.port,
                    CommunicationEndpoint.namespace_uri,
                    LDInstance.signal_profile_id,
                )
                .join(IED, IED.ied_id == CommunicationEndpoint.ied_id)
                .join(LDInstance, LDInstance.endpoint_id == CommunicationEndpoint.endpoint_id)
                .join(AssetInstance, AssetInstance.asset_instance_id == LDInstance.asset_instance_id)
                .where(LDInstance.signal_profile_id.is_not(None))
                .order_by(
                    LDInstance.signal_profile_id,
                    CommunicationEndpoint.application_protocol,
                    CommunicationEndpoint.endpoint_id,
                )
            ).all()
            servers = [
                ServerRuntimeConfigData(
                    endpoint_id=row.endpoint_id,
                    ied_name=row.ied_name,
                    asset_code=row.asset_code,
                    asset_name=row.asset_name,
                    ld_name=row.ld_name,
                    application_protocol=row.application_protocol,
                    transport=row.transport,
                    host=row.host,
                    port=row.port,
                    namespace_uri=row.namespace_uri,
                    signal_profile_id=row.signal_profile_id,
                )
                for row in rows
                if row.signal_profile_id is not None
            ]
            if not group_by or not servers:
                return servers

            supported_group_fields = {
                "signal_profile_id",
                "application_protocol",
                "transport",
                "asset_code",
                "asset_name",
                "ied_name",
                "ld_name",
            }
            unsupported_fields = sorted(set(group_by) - supported_group_fields)
            if unsupported_fields:
                raise ValueError(
                    f"Unsupported server group fields: {', '.join(unsupported_fields)}"
                )

            if not first_group_only:
                return servers

            first_group_key = tuple(getattr(servers[0], field) for field in group_by)
            return [
                server
                for server in servers
                if tuple(getattr(server, field) for field in group_by) == first_group_key
            ]

    def list_profile_items(
        self,
        signal_profile_id: int,
    ) -> list[SignalProfileItemRuntimeData]:
        """Return one signal profile's items ordered by profile item id."""
        with self._session_factory() as session:
            rows = session.execute(
                select(
                    SignalProfileItem.signal_profile_id,
                    SignalProfileItem.ln_name,
                    SignalProfileItem.do_name,
                    SignalProfileItem.relative_path,
                    ScadaDataType.type_name,
                    SignalProfileItem.default_unit,
                )
                .join(ScadaDataType, ScadaDataType.data_type_id == SignalProfileItem.data_type_id)
                .where(SignalProfileItem.signal_profile_id == signal_profile_id)
                .order_by(SignalProfileItem.profile_item_id)
            ).all()
            return [
                SignalProfileItemRuntimeData(
                    signal_profile_id=row.signal_profile_id,
                    ln_name=row.ln_name,
                    do_name=row.do_name,
                    relative_path=row.relative_path,
                    data_type=row.type_name,
                    unit=row.default_unit,
                )
                for row in rows
            ]

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
