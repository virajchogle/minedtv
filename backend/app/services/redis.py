from functools import lru_cache

import redis
import redis.asyncio as aioredis
from rq import Queue

from app.config import get_settings


@lru_cache
def get_redis() -> aioredis.Redis:
    """Async client for the API (cache, counters)."""
    return aioredis.from_url(get_settings().redis_url, decode_responses=True)


@lru_cache
def get_sync_redis() -> redis.Redis:
    """Sync client; RQ requires one (and it must not decode responses)."""
    return redis.from_url(get_settings().redis_url)


@lru_cache
def get_queue() -> Queue:
    settings = get_settings()
    return Queue(settings.queue_name, connection=get_sync_redis(), default_timeout=settings.job_timeout_s)
