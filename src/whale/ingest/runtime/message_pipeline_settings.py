"""Compatibility exports for ingest message pipeline settings."""

from __future__ import annotations

from whale.ingest.config import (
    CONFIG,
    KafkaMessageConfig,
    MessageConfig,
    RedisStreamsMessageConfig,
    RelationalOutboxMessageConfig,
)

RelationalOutboxMessageSettings = RelationalOutboxMessageConfig
# Compatibility alias kept for older imports during the transition away from file outbox.
FileOutboxMessageSettings = RelationalOutboxMessageConfig
RedisStreamsMessageSettings = RedisStreamsMessageConfig
KafkaMessageSettings = KafkaMessageConfig


class _LazyMessagePipelineSettingsProxy:
    """Lazy proxy that resolves message settings only when accessed."""

    def __getattr__(self, name: str) -> object:
        """Delegate attribute access to the current runtime message settings."""
        return getattr(CONFIG.message, name)


MESSAGE_PIPELINE_SETTINGS = _LazyMessagePipelineSettingsProxy()

__all__ = [
    "RelationalOutboxMessageSettings",
    "FileOutboxMessageSettings",
    "RedisStreamsMessageSettings",
    "KafkaMessageSettings",
    "RelationalOutboxMessageConfig",
    "RedisStreamsMessageConfig",
    "KafkaMessageConfig",
    "MessageConfig",
    "MESSAGE_PIPELINE_SETTINGS",
]
