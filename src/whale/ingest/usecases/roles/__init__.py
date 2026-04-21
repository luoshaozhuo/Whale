"""Role placeholders for future DCI-style collaboration inside use cases."""

from whale.ingest.usecases.roles.acquisition_role import AcquisitionRole
from whale.ingest.usecases.roles.health_check_role import HealthCheckRole
from whale.ingest.usecases.roles.recovery_role import RecoveryRole
from whale.ingest.usecases.roles.source_session_role import SourceSessionRole
from whale.ingest.usecases.roles.state_update_role import StateUpdateRole

__all__ = [
    "AcquisitionRole",
    "HealthCheckRole",
    "RecoveryRole",
    "SourceSessionRole",
    "StateUpdateRole",
]
