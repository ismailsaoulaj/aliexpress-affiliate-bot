# .gitignore

```
.env
node_modules/

```

# AGENTS.md

```md
# AGENTS.md — AliExpress Affiliate Bot

## Run

\`\`\`bash
source venv/bin/activate
python bot.py
\`\`\`

No tests, lint, typecheck, or formatter config exists. No `pyproject.toml`.

## Project structure

Single-module Python project (3.11). No packages, no test files.

| File | Role |
|---|---|
| `bot.py` | Entrypoint: scheduler, message formatting, send loop |
| `config.py` | Loads env vars via `python-dotenv` |
| `deals_api.py` | Fetches AliExpress Affiliate API via `python-aliexpress-api`, discount filter |
| `posted_store.py` | Redis-backed (Upstash) dedup store via `redis.asyncio` |

## Environment

`.env` is required at project root — `.env.example` documents all vars.

**Mandatory**: `BOT_TOKEN`, `CHANNEL_ID`, `ALIEXPRESS_API_KEY`, `ALIEXPRESS_API_SECRET`, `REDIS_URL`.

**Affiliate API**: Get credentials at https://openservice.aliexpress.com — the app must have `aliexpress_affiliate_product_query` permission.

**Optional**: `ADMIN_CHAT_ID`, `FETCH_INTERVAL_HOURS`, `MIN_DISCOUNT`, `ALIEXPRESS_TRACKING_ID`, `ALIEXPRESS_LANGUAGE`, `ALIEXPRESS_CURRENCY`, `ALIEXPRESS_KEYWORDS`, `ALIEXPRESS_CATEGORY_IDS`, `ALIEXPRESS_MIN_SALE_PRICE`, `ALIEXPRESS_MAX_SALE_PRICE`, `ALIEXPRESS_SHIP_TO_COUNTRY`.

The committed `.env` previously contained live secrets — do not commit changes to it.

## Behavior quirks

- If `ADMIN_CHAT_ID` is set, the bot sends an alert to that chat when AliExpress API fetch fails
- Runs once immediately on startup, then every `FETCH_INTERVAL_HOURS` (default 6)
- Queries `aliexpress_affiliate_product_query` via `python-aliexpress-api` SDK
- Uses `target_sale_price` and `target_original_price` for USD pricing; falls back to raw `sale_price`
- Filters deals with discount < `MIN_DISCOUNT` (default 40%)
- Sends `send_photo` with HTML caption; 1.5s `asyncio.sleep` between sends to avoid Telegram rate limits
- Dedup uses Upstash Redis (`REDIS_URL`) — survives container restarts
- Uses `APScheduler` AsyncIOScheduler with an idle `while True: await asyncio.sleep(3600)` loop

```

# bot.py

```py
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

```

# config.py

```py
import os

from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.environ["BOT_TOKEN"]
CHANNEL_ID = os.environ["CHANNEL_ID"]
ADMIN_CHAT_ID = os.getenv("ADMIN_CHAT_ID")

ALIEXPRESS_API_KEY = os.environ["ALIEXPRESS_API_KEY"]
ALIEXPRESS_API_SECRET = os.environ["ALIEXPRESS_API_SECRET"]
ALIEXPRESS_TRACKING_ID = os.getenv("ALIEXPRESS_TRACKING_ID")
ALIEXPRESS_LANGUAGE = os.getenv("ALIEXPRESS_LANGUAGE", "EN")
ALIEXPRESS_CURRENCY = os.getenv("ALIEXPRESS_CURRENCY", "USD")

CURRENCY_SYMBOLS: dict[str, str] = {
    "USD": "$", "SAR": "ر.س", "EUR": "€", "GBP": "£",
    "AED": "د.إ", "TRY": "₺", "EGP": "ج.م", "INR": "₹",
}
CURRENCY_SYMBOL = CURRENCY_SYMBOLS.get(ALIEXPRESS_CURRENCY, ALIEXPRESS_CURRENCY)
ALIEXPRESS_KEYWORDS = os.getenv("ALIEXPRESS_KEYWORDS")
ALIEXPRESS_CATEGORY_IDS = os.getenv("ALIEXPRESS_CATEGORY_IDS")
ALIEXPRESS_MIN_SALE_PRICE = os.getenv("ALIEXPRESS_MIN_SALE_PRICE")
ALIEXPRESS_MAX_SALE_PRICE = os.getenv("ALIEXPRESS_MAX_SALE_PRICE")
ALIEXPRESS_SHIP_TO_COUNTRY = os.getenv("ALIEXPRESS_SHIP_TO_COUNTRY")

REDIS_URL = os.environ["REDIS_URL"]

MIN_DISCOUNT = int(os.getenv("MIN_DISCOUNT", "20"))
FETCH_INTERVAL_HOURS = int(os.getenv("FETCH_INTERVAL_HOURS", "6"))

MAX_PAGES = int(os.getenv("MAX_PAGES", "5"))
PORT = int(os.getenv("PORT", "8080"))

```

# deals_api.py

```py
import logging
from dataclasses import dataclass

from aliexpress_api import AliexpressApi, models
from aliexpress_api.models.request_parameters import SortBy

logger = logging.getLogger(__name__)


@dataclass
class Deal:
    product_id: str
    title: str
    image_url: str
    old_price: float
    new_price: float
    discount_percentage: int
    rating: float
    orders_count: int
    affiliate_url: str
    shop_name: str = ""


def _parse_discount(discount_str: str | None) -> int:
    if not discount_str:
        return 0
    cleaned = discount_str.replace("%", "").strip()
    try:
        return int(float(cleaned))
    except (ValueError, TypeError):
        return 0


def _safe_float(val: str | None) -> float:
    if not val:
        return 0.0
    try:
        return float(val)
    except (ValueError, TypeError):
        return 0.0


def _safe_int(val: int | str | None) -> int:
    if val is None:
        return 0
    return int(val)


def _product_to_deal(product: models.Product) -> Deal:
    old_price = _safe_float(getattr(product, "target_original_price", None))
    new_price = _safe_float(getattr(product, "target_sale_price", None))
    if new_price == 0:
        old_price = _safe_float(getattr(product, "original_price", None))
        new_price = _safe_float(getattr(product, "sale_price", None))
    discount = _parse_discount(getattr(product, "discount", None))
    rating = _safe_float(getattr(product, "evaluate_rate", None))
    orders = _safe_int(getattr(product, "lastest_volume", None))
    affiliate_url = getattr(product, "promotion_link", None) or getattr(product, "product_detail_url", "")

    return Deal(
        product_id=str(getattr(product, "product_id", "")),
        title=getattr(product, "product_title", ""),
        image_url=getattr(product, "product_main_image_url", ""),
        old_price=old_price,
        new_price=new_price,
        discount_percentage=discount,
        rating=rating,
        orders_count=orders,
        affiliate_url=affiliate_url,
        shop_name=getattr(product, "shop_name", ""),
    )


def _filter_deals(products: list[models.Product], min_discount: int) -> list[Deal]:
    deals: list[Deal] = []
    for p in products:
        deal = _product_to_deal(p)
        if deal.discount_percentage >= min_discount and deal.new_price > 0:
            deals.append(deal)
    return deals


def fetch_aliexpress_deals(
    api_key: str,
    api_secret: str,
    tracking_id: str | None = None,
    language: str = "EN",
    currency: str = "USD",
    keywords: str | None = None,
    category_ids: str | None = None,
    min_sale_price: str | int | None = None,
    max_sale_price: str | int | None = None,
    ship_to_country: str | None = None,
    min_discount: int = 40,
    page_no: int = 1,
    page_size: int = 50,
) -> list[Deal]:
    if min_sale_price is not None and min_sale_price != "":
        min_sale_price = int(min_sale_price)
    else:
        min_sale_price = None
    if max_sale_price is not None and max_sale_price != "":
        max_sale_price = int(max_sale_price)
    else:
        max_sale_price = None
    api = AliexpressApi(
        key=api_key,
        secret=api_secret,
        language=language,
        currency=currency,
        tracking_id=tracking_id,
    )

    try:
        response = api.get_products(
            keywords=keywords or None,
            category_ids=category_ids or None,
            min_sale_price=min_sale_price or None,
            max_sale_price=max_sale_price or None,
            ship_to_country=ship_to_country or None,
            page_no=page_no,
            page_size=page_size,
            sort=SortBy.LAST_VOLUME_DESC,
        )
    except Exception:
        logger.exception("AliExpress API request failed")
        raise

    if not response.products:
        logger.info("No products returned from AliExpress API")
        return []

    deals = _filter_deals(response.products, min_discount)
    logger.info(
        "AliExpress API: %d/%d deals passed >= %d%% discount filter",
        len(deals), len(response.products), min_discount,
    )
    return deals

```

# opencode.json

```json
{
  "$schema": "https://opencode.ai/config.json",
  "mcp": {
    "github": {
      "type": "local",
      "command": ["npx", "-y", "@fre4x/github"],
      "enabled": true,
      "env": {
        "GITHUB_TOKEN": "{env:GITHUB_TOKEN}"
      }
    },
    "context7": {
      "type": "local",
      "command": ["npx", "-y", "@upstash/context7-mcp"],
      "enabled": true
    }
  }
}
```

# posted_store.py

```py
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

```

# Procfile

```
worker: python bot.py

```

# README.md

```md
# AliExpress Affiliate Bot — Home Gadgets Niche

A Telegram bot that fetches AliExpress deals from the official AliExpress Affiliate API and posts them to a Telegram channel on a scheduled interval.

Built with `python-telegram-bot` v22 (async), `APScheduler` v3, `python-aliexpress-api`, and `redis`.

## Features

- Fetches products from the official AliExpress Affiliate API (`aliexpress_affiliate_product_query`)
- Filters for deals with ≥ 40% discount (configurable)
- Posts formatted messages with photo, title, pricing, rating, and affiliate link
- Runs on a configurable schedule (every 6 hours by default)
- Deduplicates using Upstash Redis — survives container restarts
- Runs once immediately on startup, then on schedule
- Sends admin alerts on fetch failures

## Requirements

- Python 3.11+
- A Telegram Bot Token (from [@BotFather](https://t.me/BotFather))
- A Telegram channel (public or private) where the bot is admin
- AliExpress Affiliate API credentials (from [AliExpress Open Platform](https://openservice.aliexpress.com))
- An Upstash Redis instance (or any Redis-compatible service)

## Local Setup

\`\`\`bash
# Clone the repo
git clone <repo-url> && cd aliexpress-bot

# Create virtual environment
python -m venv venv && source venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Configure environment
cp .env.example .env
\`\`\`

Edit `.env` and fill in your values:

| Variable                     | Description                                          | Default                    |
| ---------------------------- | ---------------------------------------------------- | -------------------------- |
| `BOT_TOKEN`                  | Telegram Bot API token (from @BotFather)              | —                          |
| `CHANNEL_ID`                 | Channel ID (`@username` or numeric ID)                | —                          |
| `ADMIN_CHAT_ID`              | Chat ID for admin error alerts (optional)             | —                          |
| `ALIEXPRESS_API_KEY`         | AliExpress Affiliate API key                          | —                          |
| `ALIEXPRESS_API_SECRET`      | AliExpress Affiliate API secret                       | —                          |
| `ALIEXPRESS_TRACKING_ID`     | Tracking ID for affiliate links (optional)            | —                          |
| `ALIEXPRESS_LANGUAGE`        | API response language                                 | `EN`                       |
| `ALIEXPRESS_CURRENCY`        | API response currency                                 | `USD`                      |
| `ALIEXPRESS_KEYWORDS`        | Keywords to filter products (optional)                | —                          |
| `ALIEXPRESS_CATEGORY_IDS`    | Category IDs to filter by (optional)                  | —                          |
| `ALIEXPRESS_MIN_SALE_PRICE`  | Minimum sale price filter (optional)                  | —                          |
| `ALIEXPRESS_MAX_SALE_PRICE`  | Maximum sale price filter (optional)                  | —                          |
| `ALIEXPRESS_SHIP_TO_COUNTRY` | Ship-to country filter (optional)                     | —                          |
| `REDIS_URL`                  | Redis connection string (e.g. from Upstash)           | —                          |
| `FETCH_INTERVAL_HOURS`       | How often to check for new deals                      | `6`                        |
| `MIN_DISCOUNT`               | Minimum discount percentage to include                | `40`                       |

\`\`\`bash
# Run the bot
python bot.py
\`\`\`

## Railway Deployment

### Manual steps

1. Push this repo to GitHub.
2. Go to [Railway Dashboard](https://railway.app/dashboard) → **New Project** → **Deploy from GitHub repo**.
3. Railway auto-detects Python; `requirements.txt` and `runtime.txt` are picked up automatically.
4. Add the following environment variables in Railway:
   - `BOT_TOKEN`
   - `CHANNEL_ID`
   - `ALIEXPRESS_API_KEY`
   - `ALIEXPRESS_API_SECRET`
   - `REDIS_URL`
5. (Optional) Override `FETCH_INTERVAL_HOURS` or `MIN_DISCOUNT` if desired.
6. Deploy — the bot starts immediately.

> **Note:** Deduplication uses Upstash Redis (external), so history persists across restarts.

## Project Structure

\`\`\`
aliexpress-bot/
├── bot.py            # Entry point, scheduler, message sending
├── config.py         # Env variable loading
├── deals_api.py      # AliExpress Affiliate API fetcher + Deal dataclass
├── posted_store.py   # Redis-backed deduplication store
├── requirements.txt  # Python dependencies
├── runtime.txt       # Python version for Railway
└── README.md
\`\`\`

```

# requirements.txt

```txt
python-telegram-bot>=22.8,<23
httpx>=0.27,<1
APScheduler>=3.11.3,<4
python-dotenv>=1.0.0,<2
redis>=5.0,<6
python-aliexpress-api>=3.1,<4

```

# runtime.txt

```txt
3.11

```

