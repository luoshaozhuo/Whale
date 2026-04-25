"""Subscription request DTO for source subscriptions."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from whale.ingest.usecases.dtos.acquired_node_state import AcquiredNodeState
from whale.ingest.usecases.dtos.acquisition_item_data import AcquisitionItemData
from whale.ingest.usecases.dtos.source_connection_data import SourceConnectionData

SubscriptionStateHandler = Callable[[list[AcquiredNodeState]], Awaitable[None]]


@dataclass(slots=True)
class SourceSubscriptionRequest:
    """Carry the concrete request payload for one long-running subscription."""

    source_id: str
    connection: SourceConnectionData
    items: list[AcquisitionItemData]
    stop_requested: Callable[[], bool] | None = None
    state_received: SubscriptionStateHandler | None = None
