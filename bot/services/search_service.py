from __future__ import annotations

import json
from typing import Optional
import structlog

from bot.cache.redis_client import redis_get_json, redis_set_json
from bot.config import settings
from bot.database.engine import get_session
from bot.database.models import FileRecord
from bot.database.repository import FileRepository

logger = structlog.get_logger(__name__)
_CACHE_PREFIX = "search:"


def _cache_key(query: str) -> str:
    """Normalizes the inbound query string and constructs a unique Redis cache key identifier."""
    normalized = " ".join(query.lower().strip().split())
    return f"{_CACHE_PREFIX}{normalized}"


def _serialize_records(records: list[FileRecord]) -> list[dict]:
    """Serializes a sequence of database FileRecord objects into JSON-compatible dictionaries."""
    return [
        {
            "id": r.id,
            "file_hash": r.file_hash,
            "title": r.title,
            "year": r.year,
            "genre": r.genre,
            "quality": r.quality,
            "language": r.language,
            "file_type": r.file_type,
            "download_count": r.download_count,
        }
        for r in records
    ]


async def search_files(query: str) -> list[dict]:
    """Queries the Redis cache layer or executes a full-text database search for matching assets."""
    clean_query = query.strip()
    if len(clean_query) < 2:
        return []

    key = _cache_key(clean_query)
    cached = await redis_get_json(key)
    if cached is not None:
        logger.debug("search_cache_hit", query=clean_query, count=len(cached))
        return cached

    try:
        async with get_session() as session:
            repo = FileRepository(session)
            records = await repo.full_text_search(query=clean_query, limit=settings.MAX_SEARCH_RESULTS)
    except Exception as exc:
        logger.error("search_db_error", query=clean_query, error=str(exc))
        return []

    serialized = _serialize_records(records)
    
    # Save results to Redis cache (even empty array for short duration to prevent race conditions)
    cache_ttl = settings.SEARCH_CACHE_TTL if serialized else 10
    await redis_set_json(key, serialized, cache_ttl)
    
    if serialized:
        logger.info("search_completed", query=clean_query, count=len(serialized))
    else:
        logger.info("search_no_results", query=clean_query)

    return serialized


async def invalidate_search_cache() -> None:
    """Flushes all registered cache entries matching the specified search prefix from the Redis instance."""
    from bot.cache.redis_client import get_redis
    r = await get_redis()
    keys = await r.keys(f"{_CACHE_PREFIX}*")
    if keys:
        await r.delete(*keys)
        logger.info("search_cache_cleared", count=len(keys))