from __future__ import annotations

import json
from typing import Any, Optional

import redis.asyncio as aioredis
import structlog

from bot.config import settings

logger = structlog.get_logger(__name__)

_pool: Optional[aioredis.ConnectionPool] = None
_client: Optional[aioredis.Redis] = None


async def get_redis() -> aioredis.Redis:
    """Initializes a thread-safe Redis connection pool and provides the active asynchronous client instance."""
    global _pool, _client
    if _client is None:
        _pool = aioredis.ConnectionPool.from_url(
            settings.REDIS_URL,
            max_connections=settings.REDIS_MAX_CONNECTIONS,
            decode_responses=True,
        )
        _client = aioredis.Redis(connection_pool=_pool)
    return _client


async def close_redis() -> None:
    """Gracefully terminates active Redis connections and completely closes the background connection pool."""
    global _client, _pool
    if _client:
        await _client.aclose()
        _client = None
    if _pool:
        await _pool.aclose()
        _pool = None


async def redis_get(key: str) -> Optional[str]:
    """Retrieves a string value for the corresponding key reference indicator from active memory cache storage."""
    try:
        r = await get_redis()
        return await r.get(key)
    except Exception as exc:
        logger.warning("redis_get_failed", key=key, error=str(exc))
        return None


async def redis_set(key: str, value: str, ttl: int = 300) -> bool:
    """Sets a string payload key configuration mapped to an explicit Time-To-Live (TTL) expiration metric."""
    try:
        r = await get_redis()
        await r.setex(key, ttl, value)
        return True
    except Exception as exc:
        logger.warning("redis_set_failed", key=key, error=str(exc))
        return False


async def redis_delete(key: str) -> None:
    """Purges the explicit transactional storage parameter allocations identified by the target key identifier."""
    try:
        r = await get_redis()
        await r.delete(key)
    except Exception as exc:
        logger.warning("redis_delete_failed", key=key, error=str(exc))


async def redis_get_json(key: str) -> Optional[Any]:
    """Retrieves the matching cached payload asset and decodes the structural serialization parameters into JSON entities."""
    raw = await redis_get(key)
    if raw is None:
        return None
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return None


async def redis_set_json(key: str, value: Any, ttl: int = 300) -> bool:
    """Serializes arbitrary object data structures into continuous JSON text fields and commits them to memory configurations."""
    return await redis_set(key, json.dumps(value, default=str), ttl)


async def redis_incr_with_ttl(key: str, ttl: int) -> int:
    """Atomically increments transaction intervals while locking expiration constraints through pipelined command workflows."""
    try:
        r = await get_redis()
        pipe = r.pipeline()
        await pipe.incr(key)
        # Apply the explicit TTL window constraint exclusively if the key reference configuration does not possess an active timeout
        await pipe.expire(key, ttl, nx=True)
        results = await pipe.execute()
        return results[0]
    except Exception as exc:
        logger.warning("redis_incr_failed", key=key, error=str(exc))
        return 0