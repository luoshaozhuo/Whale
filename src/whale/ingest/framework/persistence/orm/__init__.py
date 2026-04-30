"""Ingest ORM models (deprecated — migrated to whale.shared.persistence.orm).

DeviceORM and SubstationORM have been removed (replaced by AssetInstance /
OrganizationLevel in whale.shared.persistence.orm).
"""

from whale.ingest.framework.persistence.orm.acquisition_model_orm import (
    AcquisitionModelORM,
)
from whale.ingest.framework.persistence.orm.acquisition_task_orm import (
    AcquisitionTaskORM,
)
from whale.ingest.framework.persistence.orm.acquisition_variable_orm import (
    AcquisitionVariableORM,
)
from whale.ingest.framework.persistence.orm.state_snapshot_outbox_orm import (
    StateSnapshotOutboxORM,
)
from whale.ingest.framework.persistence.orm.variable_state_orm import VariableStateORM

__all__ = [
    "AcquisitionModelORM",
    "AcquisitionTaskORM",
    "AcquisitionVariableORM",
    "StateSnapshotOutboxORM",
    "VariableStateORM",
]
