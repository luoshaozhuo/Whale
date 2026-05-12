"""Unit tests for OPC UA subscription batching helpers."""

from __future__ import annotations

from datetime import UTC, datetime

from whale.shared.source.models import SourceDataChange
from whale.shared.source.opcua.subscription import _deduplicate_latest_changes


def test_deduplicate_latest_changes_keeps_highest_client_sequence_per_path() -> None:
    older = SourceDataChange(path="ns=1;s=A", value=1, client_sequence=1)
    newer = SourceDataChange(path="ns=1;s=A", value=2, client_sequence=2)
    other = SourceDataChange(path="ns=1;s=B", value=3, client_sequence=3)

    result = _deduplicate_latest_changes([older, newer, other])

    assert [c.path for c in result] == ["ns=1;s=A", "ns=1;s=B"]
    assert result[0].value == 2
    assert result[1].value == 3


def test_deduplicate_latest_changes_prefers_higher_client_sequence() -> None:
    earlier = SourceDataChange(
        path="ns=1;s=A",
        value=1,
        client_sequence=10,
        source_timestamp=datetime(2026, 5, 11, 10, 5, tzinfo=UTC),
    )
    later = SourceDataChange(
        path="ns=1;s=A",
        value=2,
        client_sequence=11,
        source_timestamp=datetime(2026, 5, 11, 10, 0, tzinfo=UTC),
    )

    result = _deduplicate_latest_changes([earlier, later])

    assert len(result) == 1
    assert result[0].value == 2
