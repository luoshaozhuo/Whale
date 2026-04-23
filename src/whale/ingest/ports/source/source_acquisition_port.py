"""Source acquisition port for ingest."""

from __future__ import annotations

from typing import Protocol

from whale.ingest.usecases.dtos.acquired_node_state import AcquiredNodeState
from whale.ingest.usecases.dtos.source_acquisition_request import (
    SourceAcquisitionRequest,
)
from whale.ingest.usecases.dtos.source_subscription_request import (
    SourceSubscriptionRequest,
)


class SourceAcquisitionPort(Protocol):
    """Acquire source states from one configured source."""

    def read_once(
        self,
        request: SourceAcquisitionRequest,
    ) -> list[AcquiredNodeState]:
        """Acquire a batch of source states for one source."""

    def subscribe(self, request: SourceSubscriptionRequest) -> None:
        """Start subscription-based acquisition for one source."""
