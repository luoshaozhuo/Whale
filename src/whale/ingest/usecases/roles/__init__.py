"""Role placeholders for future DCI-style collaboration inside use cases."""

from whale.ingest.usecases.roles.pull_role import PullRole
from whale.ingest.usecases.roles.state_update_role import StateUpdateRole
from whale.ingest.usecases.roles.subscribe_role import SubscribeRole

__all__ = [
    "PullRole",
    "SubscribeRole",
    "StateUpdateRole",
]
