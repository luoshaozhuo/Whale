"""Store adapters for ingest."""

from whale.ingest.adapters.store.file_variable_state_repository import (
    FileVariableStateRepository,
)
from whale.ingest.adapters.store.sqlite_variable_state_repository import (
    SqliteVariableStateRepository,
)

__all__ = ["FileVariableStateRepository", "SqliteVariableStateRepository"]
