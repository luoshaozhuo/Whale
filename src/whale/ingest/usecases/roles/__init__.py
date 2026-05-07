"""Role placeholders for future DCI-style collaboration inside use cases."""

from whale.ingest.usecases.roles.acquisition_failure_classifier_role import (
    AcquisitionFailureClassifierRole,
)
from whale.ingest.usecases.roles.runtime_config_validation_role import (
    RuntimeConfigValidationRole,
)
from whale.ingest.usecases.roles.runtime_diagnostics_role import (
    RuntimeDiagnosticsRole,
)
from whale.ingest.usecases.roles.source_state_read_role import SourceStateReadRole
from whale.ingest.usecases.roles.state_snapshot_publish_role import (
    StateSnapshotPublishRole,
)
from whale.ingest.usecases.roles.state_snapshot_read_role import StateSnapshotReadRole
from whale.ingest.usecases.roles.state_snapshot_validation_role import (
    StateSnapshotValidationRole,
)
from whale.ingest.usecases.roles.state_update_role import StateUpdateRole
from whale.ingest.usecases.roles.subscribe_role import SubscribeRole

__all__ = [
    "AcquisitionFailureClassifierRole",
    "RuntimeConfigValidationRole",
    "RuntimeDiagnosticsRole",
    "SourceStateReadRole",
    "StateSnapshotPublishRole",
    "StateSnapshotReadRole",
    "StateSnapshotValidationRole",
    "SubscribeRole",
    "StateUpdateRole",
]
