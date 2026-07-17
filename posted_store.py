import logging

import redis.asyncio as redis

logger = logging.getLogger(__name__)

KEY_PREFIX = "aliexpress:posted"
POSTED_TTL = 7 * 86400  # 7 days


class PostedStore:
    def __init__(self, redis_url: str):
        if redis_url.startswith("redis://") and "upstash" in redis_url:
            redis_url = redis_url.replace("redis://", "rediss://", 1)
        self.r = redis.from_url(redis_url, decode_responses=True, ssl_cert_reqs=None)
        self._local: set[str] = set()

    async def is_posted(self, key: str) -> bool:
        if key in self._local:
            return True
        try:
            return bool(await self.r.exists(f"{KEY_PREFIX}:{key}"))
        except Exception:
            logger.exception("Redis exists check failed for %s", key)
            return key in self._local

    async def mark_posted(self, key: str) -> None:
        self._local.add(key)
        try:
            await self.r.set(f"{KEY_PREFIX}:{key}", "1", ex=POSTED_TTL)
        except Exception:
            logger.exception("Redis set failed for %s", key)
