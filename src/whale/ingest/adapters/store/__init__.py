"""Store adapters for ingest."""

from whale.ingest.adapters.store.counting_source_state_repository_adapter import (
    NoOpSourceStateRepositoryAdapter,
)

__all__ = ["NoOpSourceStateRepositoryAdapter"]
