# __init__.py

```py

```

# price_store.py

```py
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

```

# search_api.py

```py
import logging
import re
from typing import Optional

from aliexpress_api import AliexpressApi, models
from aliexpress_api.models.request_parameters import SortBy

logger = logging.getLogger(__name__)

PRODUCT_URL_REGEX = re.compile(r"/(\d+)\.html")


def extract_product_id(text: str) -> Optional[str]:
    match = PRODUCT_URL_REGEX.search(text)
    if match:
        return match.group(1)
    return None


def search_products(
    api_key: str,
    api_secret: str,
    query: str | None = None,
    tracking_id: str | None = None,
    category_ids: str | None = None,
    page_size: int = 20,
) -> list[models.Product]:
    api = AliexpressApi(
        key=api_key,
        secret=api_secret,
        language="AR",
        currency="SAR",
        tracking_id=tracking_id,
    )

    response = api.get_products(
        keywords=query or None,
        category_ids=category_ids or None,
        ship_to_country="SA",
        sort=SortBy.SALE_PRICE_ASC,
        page_size=page_size,
    )

    if not response or not response.products:
        return []

    return list(response.products)


def get_product_detail(
    api_key: str,
    api_secret: str,
    product_id: str,
    tracking_id: str | None = None,
) -> Optional[models.Product]:
    api = AliexpressApi(
        key=api_key,
        secret=api_secret,
        language="AR",
        currency="SAR",
        tracking_id=tracking_id,
    )

    products = api.get_products_details(product_ids=product_id)
    if products:
        return products[0]
    return None

```

# search_bot.py

```py
import asyncio
import logging
import sys
import time
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode
from telegram.error import TelegramError
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, filters

from config import (
    ALIEXPRESS_API_KEY,
    ALIEXPRESS_API_SECRET,
    ALIEXPRESS_TRACKING_ID,
    REDIS_URL,
)
from search_api import extract_product_id, search_products, get_product_detail
from price_store import PriceStore
from smart_score import smart_score, _safe_float, _parse_discount

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)
logging.getLogger("telegram").setLevel(logging.WARNING)
logger = logging.getLogger(__name__)

CATEGORY_MAP: dict[str, str] = {
    "إلكترونيات": "44",
    "ملابس": "3",
    "منزل وحديقة": "13",
    "جمال": "66",
    "ألعاب": "322",
    "أدوات": "42",
}

CATEGORY_EMOJIS: dict[str, str] = {
    "إلكترونيات": "📱",
    "ملابس": "👟",
    "منزل وحديقة": "🏠",
    "جمال": "💄",
    "ألعاب": "🎮",
    "أدوات": "🔧",
}


def _get_price(product) -> float:
    p = getattr(product, "target_sale_price", None) or getattr(product, "sale_price", "0")
    return _safe_float(p)


def _get_old_price(product) -> float:
    p = getattr(product, "target_original_price", None) or getattr(product, "original_price", "0")
    return _safe_float(p)


def _format_caption(
    product,
    price_sar: float,
    old_price_sar: float,
    discount: int,
    trend_text: Optional[str],
) -> str:
    title = getattr(product, "product_title", "")
    if len(title) > 60:
        title = title[:57].rsplit(" ", 1)[0] + "..."

    rating = _safe_float(getattr(product, "evaluate_rate", None))
    orders = getattr(product, "lastest_volume", 0) or 0

    lines = [
        f"🛒 <b>{title}</b>",
        "",
    ]

    if old_price_sar > 0:
        price_line = (
            f"💰 <s>{old_price_sar:.2f} ريال</s> → "
            f"<b>{price_sar:.2f} ريال</b> 🔥 خصم {discount}%"
        )
    else:
        price_line = f"💰 <b>{price_sar:.2f} ريال</b>"
    lines.append(price_line)

    info_parts = []
    if rating:
        info_parts.append(f"⭐ {rating}")
    if orders:
        info_parts.append(f"📦 {orders:,} طلب")
    if info_parts:
        lines.append(" | ".join(info_parts))

    lines.append("✈️ يشحن إلى السعودية")

    if trend_text:
        lines.append(trend_text)

    return "\n".join(lines)


async def _send_search_results(
    user_id: int,
    message,
    context,
    query: str = "",
    category_ids: str = None,
) -> None:
    store: PriceStore = context.bot_data.get("store")

    await message.reply_text("🔍 جاري البحث...")

    try:
        loop = asyncio.get_running_loop()
        products = await loop.run_in_executor(
            None,
            lambda: search_products(
                api_key=ALIEXPRESS_API_KEY,
                api_secret=ALIEXPRESS_API_SECRET,
                query=query or None,
                tracking_id=ALIEXPRESS_TRACKING_ID,
                category_ids=category_ids,
            ),
        )
    except Exception:
        logger.exception("Search API call failed")
        await message.reply_text("⚠️ لم نتمكن من جلب النتائج الآن. حاول مرة أخرى بعد قليل.")
        return

    if not products:
        await message.reply_text("⚠️ لم نتمكن من جلب النتائج الآن. حاول مرة أخرى بعد قليل.")
        return

    product_prices = []
    for p in products:
        price = _get_price(p)
        if price <= 0:
            continue
        discount = int(_parse_discount(getattr(p, "discount", None)))
        rating = _safe_float(getattr(p, "evaluate_rate", None))
        orders = getattr(p, "lastest_volume", 0) or 0
        product_prices.append((p, price, discount, rating, orders))

    if not product_prices:
        await message.reply_text("⚠️ لم نتمكن من جلب النتائج الآن. حاول مرة أخرى بعد قليل.")
        return

    prices_list = [pp[1] for pp in product_prices]
    max_price = max(prices_list)
    min_price = min(prices_list)

    scored = []
    for p, price, discount, rating, orders in product_prices:
        score = smart_score(price, rating, orders, discount, max_price, min_price)
        scored.append((score, p, price, discount, rating, orders))

    scored.sort(key=lambda x: x[0], reverse=True)
    top_3 = scored[:3]

    if store:
        display_query = query or list(CATEGORY_MAP.keys())[list(CATEGORY_MAP.values()).index(category_ids)] if category_ids and category_ids in CATEGORY_MAP.values() else query
        await store.save_search_history(user_id, display_query)

    sent_any = False
    for _score_val, product, price, discount, rating, orders in top_3:
        old_price = _get_old_price(product)
        product_id = str(getattr(product, "product_id", ""))
        affiliate_url = getattr(product, "promotion_link", None) or getattr(product, "product_detail_url", "")

        if store:
            await store.save_price_history(product_id, price)

        trend_text = None
        if store:
            trend_text = await store.get_price_trend(product_id, price)

        title = getattr(product, "product_title", "")
        if store:
            await store.cache_product_info(product_id, title, affiliate_url)

        caption = _format_caption(product, price, old_price, discount, trend_text)
        caption += f'\n\n🔗 <a href="{affiliate_url}">اشتري من علي إكسبرس</a>'

        image_url = getattr(product, "product_main_image_url", "")
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("🔔 نبّهني لما ينزل السعر", callback_data=f"alert:{product_id}")]
        ])

        try:
            if image_url:
                await message.reply_photo(
                    photo=image_url,
                    caption=caption,
                    parse_mode=ParseMode.HTML,
                    reply_markup=keyboard,
                )
            else:
                await message.reply_text(
                    text=caption,
                    parse_mode=ParseMode.HTML,
                    reply_markup=keyboard,
                )
            sent_any = True
        except TelegramError:
            logger.exception("Failed to send product %s", product_id)
            try:
                await message.reply_text(
                    text=caption,
                    parse_mode=ParseMode.HTML,
                    reply_markup=keyboard,
                )
                sent_any = True
            except TelegramError:
                logger.exception("Failed to send text fallback for %s", product_id)

    if not sent_any:
        await message.reply_text("⚠️ لم نتمكن من عرض النتائج. حاول مرة أخرى بعد قليل.")


async def start_command(update: Update, context) -> None:
    keyboard = []
    row = []
    for name, cat_id in CATEGORY_MAP.items():
        emoji = CATEGORY_EMOJIS.get(name, "")
        row.append(InlineKeyboardButton(f"{emoji} {name}", callback_data=f"category:{cat_id}"))
        if len(row) == 2:
            keyboard.append(row)
            row = []
    if row:
        keyboard.append(row)

    reply_markup = InlineKeyboardMarkup(keyboard)

    await update.message.reply_text(
        "👋 مرحباً بك في بوت البحث في علي إكسبرس!\n\n"
        "يمكنك البحث عن المنتجات بإرسال اسم المنتج، أو لصق رابط من علي إكسبرس للعثور على بدائل أرخص، "
        "أو استخدام الأزرار أدناه لتصفح الفئات.\n\n"
        "الأوامر المتاحة:\n"
        "/search - ابحث عن منتج\n"
        "/myalerts - اعرض تنبيهاتي\n"
        "/cancelalert - ألغِ تنبيهاً\n"
        "/history - آخر البحوثات\n"
        "/help - المساعدة",
        reply_markup=reply_markup,
    )


async def search_command(update: Update, context) -> None:
    query = " ".join(context.args)
    if not query:
        await update.message.reply_text(
            "⚠️ يرجى إدخال اسم المنتج.\n"
            "مثال: /search كفر ايفون"
        )
        return
    user_id = update.effective_user.id
    await _send_search_results(user_id, update.message, context, query=query)


async def myalerts_command(update: Update, context) -> None:
    user_id = update.effective_user.id
    store: PriceStore = context.bot_data.get("store")
    if not store:
        await update.message.reply_text("⚠️ حدث خطأ في النظام.")
        return

    alerts = await store.get_user_alerts(user_id)
    if not alerts:
        await update.message.reply_text("📭 لا يوجد لديك أي تنبيهات نشطة.")
        return

    parts = ["🔔 <b>تنبيهاتك النشطة:</b>\n"]
    for a in alerts:
        title = a.get("product_title", "")[:40]
        parts.append(
            f"🆔 <code>{a['alert_id']}</code>\n"
            f"🛒 {title}\n"
            f"💰 السعر المستهدف: {a['target_price_sar']:.2f} ريال"
        )
    await update.message.reply_text("\n---\n".join(parts), parse_mode=ParseMode.HTML)


async def cancelalert_command(update: Update, context) -> None:
    user_id = update.effective_user.id
    if not context.args:
        await update.message.reply_text(
            "⚠️ يرجى إدخال رقم التنبيه.\n"
            "مثال: /cancelalert 3\n"
            "يمكنك معرفة رقم التنبيه باستخدام /myalerts"
        )
        return
    alert_id = context.args[0].strip()
    store: PriceStore = context.bot_data.get("store")
    if not store:
        await update.message.reply_text("⚠️ حدث خطأ في النظام.")
        return

    alert = await store.get_alert(user_id, alert_id)
    if not alert:
        await update.message.reply_text("⚠️ لم يتم العثور على هذا التنبيه.")
        return

    await store.delete_alert(user_id, alert_id)
    await update.message.reply_text("✅ تم إلغاء التنبيه بنجاح.")


async def history_command(update: Update, context) -> None:
    user_id = update.effective_user.id
    store: PriceStore = context.bot_data.get("store")
    if not store:
        await update.message.reply_text("⚠️ حدث خطأ في النظام.")
        return

    history = await store.get_search_history(user_id)
    if not history:
        await update.message.reply_text("📭 لا يوجد لديك أي بحث سابق.")
        return

    keyboard = []
    for i, entry in enumerate(reversed(history)):
        query_text = entry["query"][:30]
        keyboard.append([
            InlineKeyboardButton(f"{i+1}. {query_text}", callback_data=f"history:{i}")
        ])

    await update.message.reply_text(
        "📋 <b>آخر البحوثات:</b>",
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


async def help_command(update: Update, context) -> None:
    await update.message.reply_text(
        "🤖 <b>مساعدة بوت البحث في علي إكسبرس</b>\n\n"
        "الأوامر:\n"
        "/start - ابدأ هنا واختر فئة\n"
        "/search - ابحث عن منتج: /search كفر ايفون\n"
        "/myalerts - اعرض تنبيهاتك النشطة\n"
        "/cancelalert - ألغِ تنبيهاً: /cancelalert 3\n"
        "/history - اعرض آخر 10 بحثات\n"
        "/help - اعرض جميع الأوامر\n\n"
        "يمكنك أيضاً إرسال اسم المنتج مباشرة للبحث، أو لصق رابط منتج من علي إكسبرس للعثور على بدائل أرخص.",
        parse_mode=ParseMode.HTML,
    )


async def handle_message(update: Update, context) -> None:
    user_id = update.effective_user.id
    text = update.message.text.strip()
    store: PriceStore = context.bot_data.get("store")

    if store:
        pending = await store.get_pending_alert(user_id)
        if pending:
            try:
                target_price = float(text)
                if target_price <= 0:
                    raise ValueError
            except ValueError:
                await update.message.reply_text("⚠️ يرجى إدخال رقم صحيح للسعر المستهدف.")
                return

            alert_id = str(int(time.time()))
            await store.create_alert(
                user_id=user_id,
                alert_id=alert_id,
                product_id=pending["product_id"],
                product_title=pending["title"],
                target_price_sar=target_price,
                affiliate_url=pending["affiliate_url"],
            )
            await store.clear_pending_alert(user_id)
            await update.message.reply_text(
                f"✅ تم إنشاء التنبيه بنجاح!\n"
                f"🆔 رقم التنبيه: <code>{alert_id}</code>\n"
                f"💰 ستتم إشعارتك حين يصل السعر إلى {target_price:.2f} ريال أو أقل.",
                parse_mode=ParseMode.HTML,
            )
            return

    product_id = extract_product_id(text)
    if product_id:
        await update.message.reply_text("🔍 جاري البحث عن بدائل لهذا المنتج...")
        try:
            loop = asyncio.get_running_loop()
            product = await loop.run_in_executor(
                None,
                lambda: get_product_detail(
                    api_key=ALIEXPRESS_API_KEY,
                    api_secret=ALIEXPRESS_API_SECRET,
                    product_id=product_id,
                    tracking_id=ALIEXPRESS_TRACKING_ID,
                ),
            )
        except Exception:
            logger.exception("Product detail fetch failed")
            await update.message.reply_text("⚠️ لم نتمكن من جلب معلومات المنتج. حاول مرة أخرى بعد قليل.")
            return

        if not product:
            await update.message.reply_text("⚠️ لم يتم العثور على المنتج.")
            return

        title = getattr(product, "product_title", "")
        if not title:
            await update.message.reply_text("⚠️ لم يتم العثور على معلومات المنتج.")
            return

        await _send_search_results(user_id, update.message, context, query=title)
        return

    await _send_search_results(user_id, update.message, context, query=text)


async def handle_callback_query(update: Update, context) -> None:
    query = update.callback_query
    await query.answer()
    data = query.data
    user_id = query.from_user.id
    store: PriceStore = context.bot_data.get("store")

    if data.startswith("category:"):
        cat_id = data.split(":", 1)[1]
        if not store:
            await query.message.reply_text("🔍 جاري البحث...")
        await _send_search_results(
            user_id, query.message, context, category_ids=cat_id,
        )

    elif data.startswith("alert:"):
        product_id = data.split(":", 1)[1]
        if not store:
            await query.message.reply_text("⚠️ حدث خطأ في النظام.")
            return

        cached = await store.get_cached_product_info(product_id)
        if not cached:
            await query.message.reply_text("⚠️ انتهت صلاحية هذا المنتج. يرجى البحث مرة أخرى.")
            return

        await store.set_pending_alert(
            user_id=user_id,
            product_id=product_id,
            title=cached["title"],
            affiliate_url=cached["affiliate_url"],
        )
        await query.message.reply_text(
            f"🛒 <b>{cached['title'][:50]}</b>\n\n"
            "أدخل السعر المستهدف بالريال:",
            parse_mode=ParseMode.HTML,
        )

    elif data.startswith("history:"):
        if not store:
            await query.message.reply_text("⚠️ حدث خطأ في النظام.")
            return
        index = int(data.split(":", 1)[1])
        history = await store.get_search_history(user_id)
        if index >= len(history):
            await query.message.reply_text("⚠️ هذا البحث غير متاح.")
            return
        entry = history[-(index + 1)]
        await _send_search_results(
            user_id, query.message, context, query=entry["query"],
        )


async def check_alerts(app_bot, store: PriceStore) -> None:
    logger.info("Starting alert check cycle...")
    try:
        alerts = await store.get_all_alerts()
    except Exception:
        logger.exception("Failed to fetch alerts")
        return

    if not alerts:
        logger.info("No alerts to check.")
        return

    logger.info("Checking %d alert(s)...", len(alerts))

    for alert in alerts:
        user_id = alert["user_id"]
        alert_id = alert["alert_id"]
        product_id = alert["product_id"]
        target_price = alert["target_price_sar"]
        affiliate_url = alert.get("affiliate_url", "")

        try:
            loop = asyncio.get_running_loop()
            product = await loop.run_in_executor(
                None,
                lambda pid=product_id: get_product_detail(
                    api_key=ALIEXPRESS_API_KEY,
                    api_secret=ALIEXPRESS_API_SECRET,
                    product_id=pid,
                    tracking_id=ALIEXPRESS_TRACKING_ID,
                ),
            )
        except Exception:
            logger.exception("Failed to fetch product %s for alert", product_id)
            continue

        if not product:
            try:
                await app_bot.send_message(
                    chat_id=user_id,
                    text=(
                        f"⚠️ المنتج <b>{alert['product_title'][:50]}</b> "
                        "لم يعد متاحاً. تم إلغاء التنبيه."
                    ),
                    parse_mode=ParseMode.HTML,
                )
            except TelegramError:
                logger.exception("Failed to notify user %s about unavailable product", user_id)
            await store.delete_alert(user_id, alert_id)
            continue

        current_price = _get_price(product)
        if current_price <= 0:
            continue

        if current_price <= target_price:
            title = alert.get("product_title", "")
            image_url = getattr(product, "product_main_image_url", "")
            caption = (
                f"🔔 <b>تنبيه السعر!</b>\n\n"
                f"🛒 <b>{title[:60]}</b>\n"
                f"💰 السعر الحالي: {current_price:.2f} ريال\n"
                f"🎯 السعر المستهدف: {target_price:.2f} ريال\n"
                f"✅ وصل السعر إلى المستهدف!\n\n"
                f"🔗 <a href='{affiliate_url}'>اشتري من علي إكسبرس</a>"
            )

            try:
                if image_url:
                    await app_bot.send_photo(
                        chat_id=user_id,
                        photo=image_url,
                        caption=caption,
                        parse_mode=ParseMode.HTML,
                    )
                else:
                    await app_bot.send_message(
                        chat_id=user_id,
                        text=caption,
                        parse_mode=ParseMode.HTML,
                    )
            except TelegramError:
                logger.exception("Failed to send alert notification to user %s", user_id)
                continue

            await store.delete_alert(user_id, alert_id)
            await asyncio.sleep(1.5)

    logger.info("Alert check cycle completed.")


def main() -> None:
    import os
    from dotenv import load_dotenv

    load_dotenv()
    token = os.environ.get("SEARCH_BOT_TOKEN")
    if not token:
        logger.error("SEARCH_BOT_TOKEN not set in environment")
        sys.exit(1)

    store = PriceStore(REDIS_URL)
    application = Application.builder().token(token).build()
    application.bot_data["store"] = store

    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("search", search_command))
    application.add_handler(CommandHandler("myalerts", myalerts_command))
    application.add_handler(CommandHandler("cancelalert", cancelalert_command))
    application.add_handler(CommandHandler("history", history_command))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    application.add_handler(CallbackQueryHandler(handle_callback_query))

    scheduler = AsyncIOScheduler()
    scheduler.add_job(
        check_alerts,
        "interval",
        hours=6,
        args=[application.bot, store],
    )
    scheduler.start()

    logger.info("Search Bot started — checking alerts every 6 hours.")
    application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()

```

# smart_score.py

```py
import logging

logger = logging.getLogger(__name__)


def _safe_float(val) -> float:
    if val is None:
        return 0.0
    try:
        return float(val)
    except (ValueError, TypeError):
        return 0.0


def _parse_discount(discount_str: str | None) -> float:
    if not discount_str:
        return 0.0
    cleaned = discount_str.replace("%", "").strip()
    try:
        return float(cleaned)
    except (ValueError, TypeError):
        return 0.0


def smart_score(
    price: float,
    rating: float,
    orders: int,
    discount: float,
    max_price_in_batch: float,
    min_price_in_batch: float,
) -> float:
    price_range = max_price_in_batch - min_price_in_batch
    if price_range == 0:
        price_score = 1.0
    else:
        price_score = (max_price_in_batch - price) / price_range

    rating_score = rating / 5.0
    orders_score = min(orders / 10000, 1.0)
    discount_score = discount / 100.0

    return (
        price_score * 0.35
        + rating_score * 0.30
        + orders_score * 0.20
        + discount_score * 0.15
    )

```

