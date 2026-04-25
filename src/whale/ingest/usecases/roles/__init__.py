"""Role placeholders for future DCI-style collaboration inside use cases."""

from whale.ingest.usecases.roles.pull_role import PullRole
from whale.ingest.usecases.roles.state_snapshot_publish_role import (
    StateSnapshotPublishRole,
)
from whale.ingest.usecases.roles.state_snapshot_read_role import StateSnapshotReadRole
from whale.ingest.usecases.roles.state_update_role import StateUpdateRole
from whale.ingest.usecases.roles.subscribe_role import SubscribeRole

__all__ = [
    "PullRole",
    "StateSnapshotPublishRole",
    "StateSnapshotReadRole",
    "SubscribeRole",
    "StateUpdateRole",
]
