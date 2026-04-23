"""Subscription request DTO for future source subscriptions."""

from __future__ import annotations

from dataclasses import dataclass

from whale.ingest.usecases.dtos.acquisition_item_data import AcquisitionItemData
from whale.ingest.usecases.dtos.source_connection_data import SourceConnectionData


@dataclass(slots=True)
class SourceSubscriptionRequest:
    """Carry the concrete request payload for future subscription mode."""

    runtime_config_id: int
    source_id: str
    source_name: str
    protocol: str
    connection: SourceConnectionData
    items: list[AcquisitionItemData]
