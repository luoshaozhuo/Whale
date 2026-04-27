"""State-cache adapters for ingest."""

from whale.ingest.adapters.state.redis_source_state_cache import RedisSourceStateCache
from whale.ingest.adapters.state.sqlite_source_state_cache import SqliteSourceStateCache

__all__ = ["RedisSourceStateCache", "SqliteSourceStateCache"]
