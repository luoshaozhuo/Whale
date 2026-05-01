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
    DO,
    IED,
    LD,
    LN,
)


class OpcUaSourceAcquisitionDefinitionRepository(SourceAcquisitionDefinitionPort):
    """Load OPC UA acquisition config from tasks, assets and the IED → DO hierarchy."""

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

            # Query all DOs under this IED (through DO → LN → LD join)
            do_rows = list(
                session.scalars(
                    select(DO)
                    .join(DO.ln)
                    .join(LN.ld)
                    .where(LD.ied_id == ied_id)
                    .order_by(DO.do_id)
                )
            )
            if not do_rows:
                raise LookupError(
                    f"No DO found under IED `{ied.ied_name}` for task `{task.task_id}`."
                )

            _model_id = ied.ied_name
            _asset_code = asset.asset_code
            _endpoint = task.endpoint
            _params = dict(task.params)
            _items = [
                AcquisitionItemData(
                    key=row.do_name,
                    locator=f"s={_asset_code}.{row.do_name}",
                    locator_type="node_path",
                    display_name=row.display_name or row.do_name,
                    params={},
                )
                for row in do_rows
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
