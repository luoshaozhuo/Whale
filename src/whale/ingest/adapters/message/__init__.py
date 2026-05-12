"""Message publishing adapters for ingest."""

from __future__ import annotations

from importlib import import_module

__all__ = [
    "KafkaMessagePublisher",
    "RelationalOutboxMessagePublisher",
    "RedisStreamsMessagePublisher",
]


def __getattr__(name: str) -> object:
    """Lazily expose message publishers to avoid importing unrelated backends."""

    module_by_name = {
        "KafkaMessagePublisher": "whale.ingest.adapters.message.kafka_message_publisher",
        "RedisStreamsMessagePublisher": (
            "whale.ingest.adapters.message.redis_streams_message_publisher"
        ),
        "RelationalOutboxMessagePublisher": (
            "whale.ingest.adapters.message.relational_outbox_message_publisher"
        ),
    }
    module_name = module_by_name.get(name)
    if module_name is None:
        raise AttributeError(name)
    return getattr(import_module(module_name), name)
