"""Smoke imports for access worker module."""

from __future__ import annotations

from tools.source_lab.access import worker


def test_worker_exports() -> None:
    assert callable(worker.run_worker_level)
    assert callable(worker.run_worker_entry)
    assert callable(worker.run_level_once)
