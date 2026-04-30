"""Database-backed OPC UA acquisition-definition repository for ingest."""

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
from whale.ingest.usecases.dtos.source_runtime_config_data import (
    SourceRuntimeConfigData,
)
from whale.shared.persistence.orm import (
    AcquisitionTask,
    AssetInstance,
    DA,
    IED,
)


class OpcUaSourceAcquisitionDefinitionRepository(SourceAcquisitionDefinitionPort):
    """Load OPC UA acquisition config from tasks, assets and the IED → DA hierarchy."""

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
                    f"Acquisition task `{runtime_config.runtime_config_id}` was not found."
                )

            asset = session.get(AssetInstance, task.asset_instance_id)
            if asset is None:
                raise LookupError(
                    f"AssetInstance `{task.asset_instance_id}` was not found for task `{task.task_id}`."
                )

            ied_id = task.ied_id
            if ied_id is None:
                raise LookupError(f"Task `{task.task_id}` has no ied_id configured.")

            ied = session.get(IED, ied_id)
            if ied is None:
                raise LookupError(f"IED `{ied_id}` was not found for task `{task.task_id}`.")

            # 查询该 IED 下所有启用的 DA（通过 DO → LN → LD join）
            da_rows = list(
                session.scalars(
                    select(DA)
                    .join(DA.do)
                    .join(DA.do.ln)
                    .join(DA.do.ln.ld)
                    .where(
                        DA.do.ln.ld.ied_id == ied_id,
                        DA.enabled.is_(True),
                    )
                    .order_by(DA.da_id)
                )
            )
            if not da_rows:
                raise LookupError(
                    f"No enabled DA found under IED `{ied.ied_name}` for task `{task.task_id}`."
                )

            _model_id = ied.ied_name
            _asset_code = asset.asset_code
            _endpoint = task.endpoint
            _params = dict(task.params)
            _items = [
                AcquisitionItemData(
                    key=row.da_name,
                    locator=(
                        row.locator.format(
                            device_code=_asset_code,
                            source_id=_asset_code,
                            key=row.da_name,
                        )
                        if row.locator
                        else ""
                    ),
                    locator_type=row.locator_type,
                    display_name=row.display_name or row.da_name,
                    params=dict(row.variable_params),
                )
                for row in da_rows
            ]

        return SourceAcquisitionDefinition(
            model_id=_model_id,
            connection=SourceConnectionData(
                endpoint=_endpoint,
                host=None,
                port=None,
                username=None,
                password=None,
                params=_params,
            ),
            items=_items,
        )
