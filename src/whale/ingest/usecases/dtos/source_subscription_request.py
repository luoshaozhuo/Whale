"""Subscription request DTO for future source subscriptions."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from whale.ingest.usecases.dtos.acquisition_item_data import AcquisitionItemData
from whale.ingest.usecases.dtos.source_connection_data import SourceConnectionData


@dataclass(slots=True)
class SourceSubscriptionRequest:
    """Carry the concrete request payload for future subscription mode."""

    source_id: str
    connection: SourceConnectionData
    items: list[AcquisitionItemData]
    stop_requested: Callable[[], bool] | None = None
