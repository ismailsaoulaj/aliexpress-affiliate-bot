import json
import logging
from datetime import datetime, timezone

import redis.asyncio as redis

logger = logging.getLogger(__name__)

SEARCH_HISTORY_MAX = 10
PRICE_HISTORY_MAX = 30
PRICE_HISTORY_TTL = 604800
PENDING_ALERT_TTL = 300
PRODUCT_CACHE_TTL = 3600


class PriceStore:
    def __init__(self, redis_url: str):
        if redis_url.startswith("redis://") and "upstash" in redis_url:
            redis_url = redis_url.replace("redis://", "rediss://", 1)
        self.r = redis.from_url(redis_url, decode_responses=True)

    # ------------------------------------------------------------------
    # Search history
    # ------------------------------------------------------------------

    async def save_search_history(self, user_id: int, query: str) -> None:
        key = f"search_history:{user_id}"
        try:
            data = await self.r.get(key)
            history = json.loads(data) if data else []
            history.append({
                "query": query,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            })
            if len(history) > SEARCH_HISTORY_MAX:
                history = history[-SEARCH_HISTORY_MAX:]
            await self.r.set(key, json.dumps(history))
        except Exception:
            logger.exception("Failed to save search history for user %s", user_id)

    async def get_search_history(self, user_id: int) -> list[dict]:
        key = f"search_history:{user_id}"
        try:
            data = await self.r.get(key)
            return json.loads(data) if data else []
        except Exception:
            logger.exception("Failed to get search history for user %s", user_id)
            return []

    # ------------------------------------------------------------------
    # Price history per product_id
    # ------------------------------------------------------------------

    async def save_price_history(self, product_id: str, price_sar: float) -> None:
        key = f"price_history:{product_id}"
        try:
            data = await self.r.get(key)
            history = json.loads(data) if data else []
            history.append({
                "price_sar": price_sar,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            })
            if len(history) > PRICE_HISTORY_MAX:
                history = history[-PRICE_HISTORY_MAX:]
            await self.r.set(key, json.dumps(history))
            await self.r.expire(key, PRICE_HISTORY_TTL)
        except Exception:
            logger.exception("Failed to save price history for product %s", product_id)

    async def get_price_history(self, product_id: str) -> list[dict]:
        key = f"price_history:{product_id}"
        try:
            data = await self.r.get(key)
            return json.loads(data) if data else []
        except Exception:
            logger.exception("Failed to get price history for product %s", product_id)
            return []

    async def get_price_trend(self, product_id: str, current_price: float) -> str | None:
        history = await self.get_price_history(product_id)
        if len(history) < 2:
            return None
        oldest_price = history[0]["price_sar"]
        if oldest_price == current_price:
            return None
        change_pct = abs((current_price - oldest_price) / oldest_price * 100)
        if current_price < oldest_price:
            return f"📉 انخفض السعر بنسبة {change_pct:.0f}% مقارنة بالأسبوع الماضي"
        return f"📈 ارتفع السعر بنسبة {change_pct:.0f}% مقارنة بالأسبوع الماضي"

    # ------------------------------------------------------------------
    # Product info cache (short-lived, used during alert setup)
    # ------------------------------------------------------------------

    async def cache_product_info(self, product_id: str, title: str, affiliate_url: str) -> None:
        key = f"product_cache:{product_id}"
        try:
            data = json.dumps({"title": title, "affiliate_url": affiliate_url})
            await self.r.setex(key, PRODUCT_CACHE_TTL, data)
        except Exception:
            logger.exception("Failed to cache product info for %s", product_id)

    async def get_cached_product_info(self, product_id: str) -> dict | None:
        key = f"product_cache:{product_id}"
        try:
            data = await self.r.get(key)
            return json.loads(data) if data else None
        except Exception:
            logger.exception("Failed to get cached product info for %s", product_id)
            return None

    # ------------------------------------------------------------------
    # Pending alert state (between button click and price input)
    # ------------------------------------------------------------------

    async def set_pending_alert(
        self, user_id: int, product_id: str, title: str, affiliate_url: str
    ) -> None:
        key = f"pending_alert:{user_id}"
        try:
            data = json.dumps({
                "product_id": product_id,
                "title": title,
                "affiliate_url": affiliate_url,
            })
            await self.r.setex(key, PENDING_ALERT_TTL, data)
        except Exception:
            logger.exception("Failed to set pending alert for user %s", user_id)

    async def get_pending_alert(self, user_id: int) -> dict | None:
        key = f"pending_alert:{user_id}"
        try:
            data = await self.r.get(key)
            return json.loads(data) if data else None
        except Exception:
            logger.exception("Failed to get pending alert for user %s", user_id)
            return None

    async def clear_pending_alert(self, user_id: int) -> None:
        key = f"pending_alert:{user_id}"
        try:
            await self.r.delete(key)
        except Exception:
            logger.exception("Failed to clear pending alert for user %s", user_id)

    # ------------------------------------------------------------------
    # Alerts
    # ------------------------------------------------------------------

    async def create_alert(
        self,
        user_id: int,
        alert_id: str,
        product_id: str,
        product_title: str,
        target_price_sar: float,
        affiliate_url: str,
    ) -> None:
        alert_key = f"alert:{user_id}:{alert_id}"
        index_key = f"alert_index:{user_id}"
        try:
            data = json.dumps({
                "alert_id": alert_id,
                "product_id": product_id,
                "product_title": product_title,
                "target_price_sar": target_price_sar,
                "affiliate_url": affiliate_url,
                "created_at": datetime.now(timezone.utc).isoformat(),
            })
            await self.r.set(alert_key, data)
            await self.r.sadd(index_key, alert_id)
        except Exception:
            logger.exception("Failed to create alert for user %s", user_id)

    async def get_user_alerts(self, user_id: int) -> list[dict]:
        index_key = f"alert_index:{user_id}"
        try:
            alert_ids = await self.r.smembers(index_key)
            alerts = []
            for alert_id in alert_ids:
                alert_key = f"alert:{user_id}:{alert_id}"
                data = await self.r.get(alert_key)
                if data:
                    alerts.append(json.loads(data))
                else:
                    await self.r.srem(index_key, alert_id)
            return alerts
        except Exception:
            logger.exception("Failed to get user alerts for user %s", user_id)
            return []

    async def get_alert(self, user_id: int, alert_id: str) -> dict | None:
        alert_key = f"alert:{user_id}:{alert_id}"
        try:
            data = await self.r.get(alert_key)
            return json.loads(data) if data else None
        except Exception:
            logger.exception("Failed to get alert %s for user %s", alert_id, user_id)
            return None

    async def delete_alert(self, user_id: int, alert_id: str) -> None:
        alert_key = f"alert:{user_id}:{alert_id}"
        index_key = f"alert_index:{user_id}"
        try:
            await self.r.delete(alert_key)
            await self.r.srem(index_key, alert_id)
        except Exception:
            logger.exception("Failed to delete alert %s for user %s", alert_id, user_id)

    async def get_all_alert_user_ids(self) -> list[int]:
        try:
            user_ids = []
            async for key in self.r.scan_iter("alert_index:*"):
                user_id = int(key.split(":", 1)[1])
                user_ids.append(user_id)
            return user_ids
        except Exception:
            logger.exception("Failed to scan alert_index keys")
            return []

    async def get_all_alerts(self) -> list[dict]:
        alerts = []
        user_ids = await self.get_all_alert_user_ids()
        for uid in user_ids:
            user_alerts = await self.get_user_alerts(uid)
            for a in user_alerts:
                a["user_id"] = uid
                alerts.append(a)
        return alerts
