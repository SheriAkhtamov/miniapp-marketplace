import json
from typing import Optional, Any
from redis.asyncio import Redis
from app.config import settings
from app.utils.logger import logger

_redis: Optional[Redis] = None


async def get_redis() -> Redis:
    global _redis
    if _redis is None:
        _redis = Redis.from_url(settings.REDIS_URL, decode_responses=True)
    return _redis


async def close_redis():
    global _redis
    if _redis:
        await _redis.close()
        _redis = None


async def cache_get(key: str) -> Optional[Any]:
    try:
        r = await get_redis()
        val = await r.get(key)
        if val is not None:
            return json.loads(val)
    except Exception:
        logger.opt(exception=True).debug("Redis cache_get error")
    return None


async def cache_set(key: str, value: Any, ttl: int = None):
    if ttl is None:
        ttl = settings.CACHE_TTL
    try:
        r = await get_redis()
        await r.set(key, json.dumps(value, default=str), ex=ttl)
    except Exception:
        logger.opt(exception=True).debug("Redis cache_set error")


async def cache_delete(key: str):
    try:
        r = await get_redis()
        await r.delete(key)
    except Exception:
        logger.opt(exception=True).debug("Redis cache_delete error")


async def cache_delete_pattern(pattern: str):
    try:
        r = await get_redis()
        cursor = 0
        while True:
            cursor, keys = await r.scan(cursor, match=pattern, count=100)
            if keys:
                await r.delete(*keys)
            if cursor == 0:
                break
    except Exception:
        logger.opt(exception=True).debug("Redis cache_delete_pattern error")
