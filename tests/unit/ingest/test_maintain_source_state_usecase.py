"""Unit tests for the maintain-source-state use case."""

from __future__ import annotations

from whale.ingest.usecases.dtos.maintain_source_state_command import (
    MaintainSourceStateCommand,
)
from whale.ingest.usecases.dtos.normalized_point_event import NormalizedPointEvent
from whale.ingest.usecases.maintain_source_state_usecase import (
    MaintainSourceStateUseCase,
)


class FakeSourceAcquisitionPort:
    """Fake source acquisition port for unit tests."""

    def __init__(self, events: list[NormalizedPointEvent]) -> None:
        """Store the events that should be returned by the fake."""
        self._events = list(events)
        self.called_with: list[str] = []

    def acquire(self, source_id: str) -> list[NormalizedPointEvent]:
        """Return the preconfigured events for the requested source."""
        self.called_with.append(source_id)
        return list(self._events)


class FakePointStateStorePort:
    """Fake state store port for unit tests."""

    def __init__(self) -> None:
        """Initialize captured calls for later assertions."""
        self.calls: list[tuple[str, list[NormalizedPointEvent]]] = []

    def upsert_many(
        self,
        source_id: str,
        events: list[NormalizedPointEvent],
    ) -> int:
        """Capture the store call and return the number of events."""
        copied_events = list(events)
        self.calls.append((source_id, copied_events))
        return len(copied_events)


def test_execute_updates_state_for_received_events() -> None:
    """Execute one maintenance step with two received events."""
    events = [
        NormalizedPointEvent(point_id="p1", value=1),
        NormalizedPointEvent(point_id="p2", value=2),
    ]
    acquisition_port = FakeSourceAcquisitionPort(events)
    store_port = FakePointStateStorePort()
    use_case = MaintainSourceStateUseCase(acquisition_port, store_port)

    result = use_case.execute(MaintainSourceStateCommand(source_id="source-a"))

    assert acquisition_port.called_with == ["source-a"]
    assert store_port.calls == [("source-a", events)]
    assert result.source_id == "source-a"
    assert result.received_count == 2
    assert result.updated_count == 2


def test_execute_returns_zero_counts_when_no_events_received() -> None:
    """Execute one maintenance step with no received events."""
    acquisition_port = FakeSourceAcquisitionPort([])
    store_port = FakePointStateStorePort()
    use_case = MaintainSourceStateUseCase(acquisition_port, store_port)

    result = use_case.execute(MaintainSourceStateCommand(source_id="source-b"))

    assert acquisition_port.called_with == ["source-b"]
    assert store_port.calls == [("source-b", [])]
    assert result.source_id == "source-b"
    assert result.received_count == 0
    assert result.updated_count == 0
