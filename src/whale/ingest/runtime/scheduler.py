"""Minimal runtime scheduler for ingest sources."""

from __future__ import annotations

import time

from whale.ingest.ports.source.source_runtime_config_port import (
    SourceRuntimeConfigPort,
)
from whale.ingest.usecases.dtos.maintain_source_state_command import (
    MaintainSourceStateCommand,
)
from whale.ingest.usecases.dtos.source_runtime_config_data import (
    SourceRuntimeConfigData,
)
from whale.ingest.usecases.maintain_source_state_usecase import (
    MaintainSourceStateUseCase,
)


class SourceScheduler:
    """Dispatch source executions according to runtime configuration."""

    def __init__(
        self,
        runtime_config_port: SourceRuntimeConfigPort,
        use_case: MaintainSourceStateUseCase,
        loop_interval_seconds: float = 1.0,
    ) -> None:
        """Initialize the scheduler with runtime config and one-step use case."""
        self._runtime_config_port = runtime_config_port
        self._use_case = use_case
        self._loop_interval_seconds = loop_interval_seconds
        self._executed_once_sources: set[str] = set()
        self._started_subscription_sources: set[str] = set()
        self._next_poll_due_at: dict[str, float] = {}

    def run(self) -> None:
        """Run the minimal scheduling loop forever."""
        while True:
            configs = self._runtime_config_port.get_enabled_sources()
            self._prune_missing_sources(configs)

            for cfg in configs:
                if cfg.acquisition_mode == "ONCE":
                    self.run_once(cfg)
                elif cfg.acquisition_mode == "POLLING":
                    self.run_polling(cfg)
                elif cfg.acquisition_mode == "SUBSCRIPTION":
                    self.run_subscription(cfg)

            time.sleep(self._loop_interval_seconds)

    def run_once(self, config: SourceRuntimeConfigData) -> None:
        """Execute one source only once for the scheduler lifetime."""
        if config.source_id in self._executed_once_sources:
            return

        self._execute_source(config.source_id)
        self._executed_once_sources.add(config.source_id)

    def run_polling(self, config: SourceRuntimeConfigData) -> None:
        """Execute one source according to its polling interval."""
        now = time.monotonic()
        next_due_at = self._next_poll_due_at.get(config.source_id)
        if next_due_at is not None and now < next_due_at:
            return

        self._execute_source(config.source_id)
        interval_seconds = max(config.interval_ms, 0) / 1000
        self._next_poll_due_at[config.source_id] = now + interval_seconds

    def run_subscription(self, config: SourceRuntimeConfigData) -> None:
        """Execute one source once to bootstrap subscription mode."""
        if config.source_id in self._started_subscription_sources:
            return

        self._execute_source(config.source_id)
        self._started_subscription_sources.add(config.source_id)

    def _execute_source(self, source_id: str) -> None:
        """Run the one-step use case for one source."""
        self._use_case.execute(MaintainSourceStateCommand(source_id=source_id))

    def _prune_missing_sources(
        self,
        configs: list[SourceRuntimeConfigData],
    ) -> None:
        """Drop scheduler state for sources that are no longer enabled."""
        active_source_ids = {config.source_id for config in configs}
        self._next_poll_due_at = {
            source_id: due_at
            for source_id, due_at in self._next_poll_due_at.items()
            if source_id in active_source_ids
        }
        self._started_subscription_sources.intersection_update(active_source_ids)
