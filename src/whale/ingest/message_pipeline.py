"""Message pipeline abstractions for ingest output."""

from __future__ import annotations

from typing import Protocol


class IngestMessagePipeline(Protocol):
    """Protocol for sending collected ingest records to a downstream pipeline."""

    def publish(self, records: list[object]) -> None:
        """Publish one collected batch to the downstream pipeline."""


class InMemoryIngestMessagePipeline:
    """Simple in-memory message pipeline used by tests and local runs."""

    def __init__(self) -> None:
        """Initialize empty published-batch storage."""
        self._batches: list[list[object]] = []

    def publish(self, records: list[object]) -> None:
        """Store one collected batch in memory.

        Args:
            records: Collected ingest records from one polling step.
        """
        self._batches.append(list(records))

    def batches(self) -> list[list[object]]:
        """Return all published batches."""
        return [list(batch) for batch in self._batches]
