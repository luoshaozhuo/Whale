"""DTOs for ingest snapshot message publishing results."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(slots=True)
class MessagePublishResult:
    """Represent the outcome of publishing one snapshot message."""

    pipeline_name: str
    success: bool
    message_id: str
    message_count: int
    published_at: datetime
    error_message: str | None = None
