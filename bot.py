import asyncio
import logging
import re

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from telegram import Bot, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode
from telegram.error import TelegramError

from config import (
    ADMIN_CHAT_ID,
    ALIEXPRESS_API_KEY,
    ALIEXPRESS_API_SECRET,
    ALIEXPRESS_TRACKING_ID,
    ALIEXPRESS_LANGUAGE,
    ALIEXPRESS_CURRENCY,
    ALIEXPRESS_KEYWORDS,
    ALIEXPRESS_CATEGORY_IDS,
    ALIEXPRESS_MIN_SALE_PRICE,
    ALIEXPRESS_MAX_SALE_PRICE,
    ALIEXPRESS_SHIP_TO_COUNTRY,
    BOT_TOKEN,
    CHANNEL_ID,
    CURRENCY_SYMBOL,
    FETCH_INTERVAL_HOURS,
    MAX_PAGES,
    MIN_DISCOUNT,
    PORT,
    REDIS_URL,
)
from deals_api import Deal, fetch_aliexpress_deals
from posted_store import PostedStore

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


CAPTION_LIMIT = 1024
POST_DELAY = 10
_current_page = 1


def _format_caption(deal: Deal) -> str:
    title = deal.title
    if len(title) > 80:
        title = title[:77].rsplit(" ", 1)[0] + "..."

    old = f"{deal.old_price:.2f} {CURRENCY_SYMBOL}" if deal.old_price else "غير متوفر"
    new = f"{deal.new_price:.2f} {CURRENCY_SYMBOL}"

    lines = [
        f"<b>{title}</b>",
        "",
        f"السعر: <s>{old}</s> → <b>{new} (خصم {deal.discount_percentage}%! 🔥)</b>",
        "",
    ]

    info = []
    if deal.rating:
        info.append(f"⭐ <b>{deal.rating}</b>/5")
    if deal.orders_count:
        info.append(f"📦 <b>{deal.orders_count:,}+</b> تم البيع")
    if info:
        lines.append("  •  ".join(info))

    if deal.shop_name:
        lines.append(f"المتجر:  {deal.shop_name}")

    result = "\n".join(lines)

    if len(result) > CAPTION_LIMIT:
        lines = [l for l in result.split("\n") if not l.startswith(("🏪", "⭐", "📦"))]
        result = "\n".join(lines)

    return result[:CAPTION_LIMIT]


async def _notify_admin(bot: Bot, message: str) -> None:
    if not ADMIN_CHAT_ID:
        return
    try:
        await bot.send_message(chat_id=ADMIN_CHAT_ID, text=message)
    except TelegramError:
        logger.exception("Failed to notify admin")


async def _send_with_retry(bot: Bot, chat_id: str, photo: str, caption: str, deal_title: str, reply_markup=None) -> bool:
    for attempt in range(3):
        try:
            await bot.send_photo(
                chat_id=chat_id,
                photo=photo,
                caption=caption,
                parse_mode=ParseMode.HTML,
                reply_markup=reply_markup,
            )
            return True
        except TelegramError as exc:
            msg = str(exc)
            m = re.search(r"Retry in (\d+)", msg)
            if m:
                wait = int(m.group(1)) + 2
                logger.warning("Flood for '%s' — retry in %ds (attempt %d/3)", deal_title, wait, attempt + 1)
                await asyncio.sleep(wait)
                continue
            logger.error("Failed to send deal '%s': %s", deal_title, exc)
            return False
    logger.error("Gave up on '%s' after 3 attempts", deal_title)
    return False


async def check_and_publish(bot: Bot, store: PostedStore) -> None:
    global _current_page
    try:
        loop = asyncio.get_running_loop()
        deals = await loop.run_in_executor(
            None,
            lambda: fetch_aliexpress_deals(
                api_key=ALIEXPRESS_API_KEY,
                api_secret=ALIEXPRESS_API_SECRET,
                tracking_id=ALIEXPRESS_TRACKING_ID,
                language=ALIEXPRESS_LANGUAGE,
                currency=ALIEXPRESS_CURRENCY,
                keywords=ALIEXPRESS_KEYWORDS,
                category_ids=ALIEXPRESS_CATEGORY_IDS,
                min_sale_price=ALIEXPRESS_MIN_SALE_PRICE,
                max_sale_price=ALIEXPRESS_MAX_SALE_PRICE,
                ship_to_country=ALIEXPRESS_SHIP_TO_COUNTRY,
                min_discount=MIN_DISCOUNT,
                page_no=_current_page,
            ),
        )
    except Exception as exc:
        logger.error("Feed fetch failed: %s", exc)
        await _notify_admin(
            bot,
            f"⚠️ AliExpress API fetch failed.\n\n{exc}",
        )
        return

    new_deals: list[Deal] = []
    for d in deals:
        if not await store.is_posted(d.product_id):
            new_deals.append(d)

    if not new_deals:
        logger.info("No new deals found on page %d/%d.", _current_page, MAX_PAGES)
        _current_page = (_current_page % MAX_PAGES) + 1
        return

    logger.info("Found %d new deal(s) on page %d/%d. Posting…", len(new_deals), _current_page, MAX_PAGES)

    for i, deal in enumerate(new_deals):
        caption = _format_caption(deal)
        button = InlineKeyboardButton("🛒 اشتري الآن", url=deal.affiliate_url)
        keyboard = InlineKeyboardMarkup([[button]])

        ok = await _send_with_retry(bot, CHANNEL_ID, deal.image_url, caption, deal.title, reply_markup=keyboard)
        if not ok:
            continue

        await store.mark_posted(deal.product_id)
        logger.info("Posted (%d/%d): %s", i + 1, len(new_deals), deal.title[:60])

        if i < len(new_deals) - 1:
            await asyncio.sleep(POST_DELAY)

    _current_page = (_current_page % MAX_PAGES) + 1


async def _handle_health(reader, writer):
    writer.write(b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\n\r\nok")
    await writer.drain()
    writer.close()


async def _run_health_server():
    try:
        server = await asyncio.start_server(_handle_health, host="0.0.0.0", port=PORT)
        logger.info("Health check server listening on port %d", PORT)
        await server.serve_forever()
    except OSError:
        logger.warning("Health check server could not bind to port %d", PORT)


async def main() -> None:
    bot = Bot(token=BOT_TOKEN)
    store = PostedStore(REDIS_URL)

    asyncio.create_task(_run_health_server())

    scheduler = AsyncIOScheduler()
    scheduler.add_job(
        check_and_publish,
        "interval",
        hours=FETCH_INTERVAL_HOURS,
        args=[bot, store],
    )
    scheduler.start()

    logger.info(
        "Bot started — checking every %d hour(s). Running once immediately.",
        FETCH_INTERVAL_HOURS,
    )

    await check_and_publish(bot, store)

    try:
        while True:
            await asyncio.sleep(3600)
    except (KeyboardInterrupt, SystemExit):
        scheduler.shutdown(wait=False)


if __name__ == "__main__":
    asyncio.run(main())
