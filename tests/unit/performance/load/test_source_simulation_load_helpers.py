from __future__ import annotations

import importlib

from whale.shared.scheduling import even_stagger_offset


def test_start_offset_for_worker_returns_zero_in_none_mode(monkeypatch) -> None:
    monkeypatch.setenv("SOURCE_SIM_LOAD_STAGGER_MODE", "none")
    module = importlib.import_module("tests.performance.load.test_source_simulation_load")
    module = importlib.reload(module)

    assert module._start_offset_for_worker(
        worker_index=2,
        worker_count=4,
        target_interval_s=0.1,
    ) == 0.0


def test_start_offset_for_worker_uses_even_stagger(monkeypatch) -> None:
    monkeypatch.setenv("SOURCE_SIM_LOAD_STAGGER_MODE", "even")
    module = importlib.import_module("tests.performance.load.test_source_simulation_load")
    module = importlib.reload(module)

    assert module._start_offset_for_worker(
        worker_index=2,
        worker_count=4,
        target_interval_s=0.1,
    ) == even_stagger_offset(
        worker_index=2,
        worker_count=4,
        interval_seconds=0.1,
    )
