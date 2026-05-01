"""Whale 共享 ORM 模型."""

from whale.shared.persistence.orm.acquisition import (
    AcquisitionTask,
    DOState,
    StateSnapshotOutbox,
)
from whale.shared.persistence.orm.asset import (
    AssetBOM,
    AssetInstance,
    AssetType,
    ComponentInstance,
    ComponentType,
    WindTurbineBOMView,
)
from whale.shared.persistence.orm.asset_attribute import AssetAttribute
from whale.shared.persistence.orm.asset_model import AssetModel
from whale.shared.persistence.orm.component_attribute import ComponentAttribute
from whale.shared.persistence.orm.component_model import ComponentModel
from whale.shared.persistence.orm.organization import Organization
from whale.shared.persistence.orm.scada_model import (
    AcqDOStateDetailView,
    AssetModelDetailView,
    CDCDict,
    ComponentModelDetailView,
    DO,
    FCDict,
    IED,
    LD,
    LN,
    MeasurementPointView,
    ScadaDataType,
)
from whale.shared.persistence.orm.topology import (
    ElectricalTopology,
    NetworkTopology,
)

__all__ = [
    "Organization",
    "AssetType", "AssetInstance", "AssetBOM", "WindTurbineBOMView",
    "ComponentType", "ComponentInstance",
    "AssetModel", "ComponentModel",
    "AssetAttribute", "ComponentAttribute",
    "IED", "LD", "LN", "DO", "ScadaDataType", "CDCDict", "FCDict",
    "MeasurementPointView", "AssetModelDetailView", "ComponentModelDetailView",
    "AcqDOStateDetailView",
    "AcquisitionTask", "DOState", "StateSnapshotOutbox",
    "ElectricalTopology", "NetworkTopology",
]
